# -*- coding: utf-8 -*-
import os
import threading
import time
import re
from datetime import datetime
from flask import Flask, request, redirect, render_template_string
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 300*1024*1024
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get("PORT",8080))

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= ابزار =================
def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def detect_platform(url):
    url=url.lower()
    if "youtube" in url or "youtu.be" in url:
        return "YouTube"
    if "tiktok" in url:
        return "TikTok"
    if "instagram" in url:
        return "Instagram"
    if "twitter" in url or "x.com" in url:
        return "Twitter"
    if "facebook" in url:
        return "Facebook"
    return "Other"

# ================= دیتابیس =================
class Database:
    def __init__(self):
        self.conn=sqlite3.connect("database/bot.db",check_same_thread=False)
        self.cursor=self.conn.cursor()
        self.init_db()

    def init_db(self):
        # جدول کاربران
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TIMESTAMP,
            last_use TIMESTAMP,
            download_count INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
        """)
        # جدول گروه‌ها
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups(
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_date TIMESTAMP,
            last_active TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """)
        # جدول دانلودها
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            url TEXT,
            format TEXT,
            size INTEGER,
            timestamp TIMESTAMP,
            source TEXT,
            platform TEXT
        )
        """)
        # جدول تنظیمات
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        # پیش‌فرض‌ها
        defaults=[
            ("bot_status","ON"),
            ("total_users","0"),
            ("total_downloads","0"),
            ("total_groups","0")
        ]
        for k,v in defaults:
            self.cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
        # ادمین اصلی
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id,is_admin) VALUES(?,1)",(ADMIN_ID,))
        self.conn.commit()

    # مدیریت کاربران
    def add_user(self,user_id,username,first_name):
        now=datetime.now()
        self.cursor.execute("SELECT * FROM users WHERE user_id=?",(user_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE users SET last_use=?, username=?, first_name=? WHERE user_id=?",
                                (now,username,first_name,user_id))
        else:
            self.cursor.execute("""
            INSERT INTO users(user_id,username,first_name,joined_date,last_use)
            VALUES(?,?,?,?,?)
            """,(user_id,username,first_name,now,now))
            total=int(self.get_setting("total_users"))
            self.set_setting("total_users",str(total+1))
        self.conn.commit()

    def add_group(self,chat_id,title):
        now=datetime.now()
        self.cursor.execute("SELECT * FROM groups WHERE chat_id=?",(chat_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE groups SET last_active=?, title=? WHERE chat_id=?",(now,title,chat_id))
        else:
            self.cursor.execute("""
            INSERT INTO groups(chat_id,title,added_date,last_active)
            VALUES(?,?,?,?)
            """,(chat_id,title,now,now))
            total=int(self.get_setting("total_groups"))
            self.set_setting("total_groups",str(total+1))
        self.conn.commit()

    def add_download(self,user_id,chat_id,url,format_type,size,source,platform):
        now=datetime.now()
        self.cursor.execute("""
        INSERT INTO downloads(user_id,chat_id,url,format,size,timestamp,source,platform)
        VALUES(?,?,?,?,?,?,?,?)
        """,(user_id,chat_id,url,format_type,size,now,source,platform))
        self.cursor.execute("UPDATE users SET download_count=download_count+1 WHERE user_id=?",(user_id,))
        total=int(self.get_setting("total_downloads"))
        self.set_setting("total_downloads",str(total+1))
        self.conn.commit()

    def get_setting(self,key):
        self.cursor.execute("SELECT value FROM settings WHERE key=?",(key,))
        r=self.cursor.fetchone()
        return r[0] if r else "0"

    def set_setting(self,key,val):
        self.cursor.execute("UPDATE settings SET value=? WHERE key=?",(val,key))
        self.conn.commit()

    def is_blocked(self,user_id):
        self.cursor.execute("SELECT is_blocked FROM users WHERE user_id=?",(user_id,))
        r=self.cursor.fetchone()
        return r and r[0]==1

    def block_user(self,user_id):
        self.cursor.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(user_id,))
        self.conn.commit()

    def unblock_user(self,user_id):
        self.cursor.execute("UPDATE users SET is_blocked=0 WHERE user_id=?",(user_id,))
        self.conn.commit()

    def get_users(self,limit=20):
        self.cursor.execute("""
        SELECT user_id, username, first_name, download_count, is_blocked
        FROM users ORDER BY last_use DESC LIMIT ?
        """,(limit,))
        return self.cursor.fetchall()

    def get_recent_downloads(self,limit=10):
        self.cursor.execute("""
        SELECT user_id,url,platform,timestamp FROM downloads ORDER BY timestamp DESC LIMIT ?
        """,(limit,))
        return self.cursor.fetchall()

db=Database()
bot=telebot.TeleBot(TOKEN)
app=Flask(__name__)

# ================= دانلود =================
def download_video(url,chat_id,user_id,is_group=False):
    try:
        platform=detect_platform(url)
        ydl_opts={
            "quiet":True,
            "no_warnings":True,
            "outtmpl":f"{DOWNLOAD_PATH}/%(title)s.%(ext)s",
            "format":"bestvideo+bestaudio/best",
            "max_filesize":MAX_FILE_SIZE
        }
        msg=bot.send_message(chat_id,f"⏳ در حال دانلود از {platform} ...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info=ydl.extract_info(url,download=True)

        if not info:
            bot.edit_message_text("❌ خطا در دریافت اطلاعات",chat_id,msg.message_id)
            return

        title=clean_filename(info.get("title","file"))
        filename=None
        for f in os.listdir(DOWNLOAD_PATH):
            if title in f:
                filename=os.path.join(DOWNLOAD_PATH,f)
                break

        if not filename or not os.path.exists(filename):
            bot.edit_message_text("❌ فایل پیدا نشد",chat_id,msg.message_id)
            return

        size=os.path.getsize(filename)
        if size>MAX_FILE_SIZE:
            os.remove(filename)
            bot.edit_message_text("❌ حجم فایل بیشتر از 300MB",chat_id,msg.message_id)
            return

        bot.edit_message_text("📤 در حال آپلود ...",chat_id,msg.message_id)

        with open(filename,"rb") as f:
            if filename.endswith((".mp4",".mkv",".webm")):
                bot.send_video(chat_id,f,caption=f"✅ {title}")
                format_type="video"
            elif filename.endswith(".mp3"):
                bot.send_audio(chat_id,f,caption=f"✅ {title}")
                format_type="audio"
            else:
                bot.send_document(chat_id,f,caption=f"✅ {title}")
                format_type="file"

        source="group" if is_group else "private"
        db.add_download(user_id,chat_id,url,format_type,size,source,platform)
        os.remove(filename)
        bot.delete_message(chat_id,msg.message_id)

    except Exception as e:
        bot.send_message(chat_id,f"❌ خطا:\n{str(e)[:200]}")

# ================= دستورات =================
@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id,message.from_user.username,message.from_user.first_name)
    bot.reply_to(message,"🎬 لینک بفرست تا دانلود کنم")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id!=ADMIN_ID:
        return
    status=db.get_setting("bot_status")
    users=db.get_users(10)
    downloads=db.get_recent_downloads(10)
    markup=InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🟢 روشن",callback_data="on"))
    markup.add(InlineKeyboardButton("🔴 خاموش",callback_data="off"))
    text=f"وضعیت ربات: {status}\n\nآخرین کاربران:\n"
    for u in users:
        text+=f"{u[0]} | {u[2] or u[1]} | دانلود: {u[3]} | {'🔒' if u[4] else '✅'}\n"
    text+="\nآخرین دانلودها:\n"
    for d in downloads:
        text+=f"{d[0]} | {d[1]} | {d[2]} | {d[3][:16]}\n"
    bot.send_message(message.chat.id,text,reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    if call.data in ["on","off"]:
        if call.from_user.id!=ADMIN_ID:
            bot.answer_callback_query(call.id,"⛔ دسترسی ندارید")
            return
        db.set_setting("bot_status","ON" if call.data=="on" else "OFF")
        bot.edit_message_text(f"وضعیت جدید: {call.data.upper()}",call.message.chat.id,call.message.message_id)

# ================= پردازش پیام =================
@bot.message_handler(func=lambda m: True,content_types=['text'])
def handle_message(message):
    if db.get_setting("bot_status")=="OFF": return
    if db.is_blocked(message.from_user.id): return
    db.add_user(message.from_user.id,message.from_user.username,message.from_user.first_name)
    urls=extract_urls(message.text)
    if not urls: return
    url=urls[0]
    bot.reply_to(message,"✅ لینک دریافت شد، شروع دانلود...")
    threading.Thread(target=download_video,args=(url,message.chat.id,message.from_user.id,message.chat.type in ["group","supergroup"]),daemon=True).start()

# ================= وب پنل =================
HTML_TEMPLATE="""
<html><head><meta charset="utf-8"><title>Bot Panel</title></head>
<body style="font-family:tahoma;text-align:center">
<h2>پنل مدیریت ربات</h2>
<p>وضعیت: {{status}}</p>
<a href="/toggle/on">🟢 روشن</a> | <a href="/toggle/off">🔴 خاموش</a>
</body></html>
"""
@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE,status=db.get_setting("bot_status"))
@app.route('/toggle/<status>')
def toggle(status):
    if status in ["on","off"]: db.set_setting("bot_status","ON" if status=="on" else "OFF")
    return redirect('/')
@app.route('/webhook',methods=['POST'])
def webhook():
    json_str=request.get_data().decode('utf-8')
    update=telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK",200

# ================= اجرا =================
if __name__=="__main__":
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("🚀 ربات آماده است")
    app.run(host="0.0.0.0",port=PORT)
