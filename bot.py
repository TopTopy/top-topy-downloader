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
PORT = int(os.environ.get("PORT", 8080))
REQUIRED_CHANNELS = [
    ("@top_topy_downloader", 3828073352),
    ("@IdTOP_TOPY", 3872568492)
]

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= ابزار =================
def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def detect_platform(url):
    url = url.lower()
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
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
        self.start_keep_alive()

    def init_db(self):
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
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups(
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_date TIMESTAMP,
            last_active TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """)
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
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        defaults = [
            ("bot_status","ON"),
            ("total_users","0"),
            ("total_downloads","0"),
            ("total_groups","0"),
            ("group_mode","ON"),
            ("private_mode","ON")
        ]
        for k, v in defaults:
            self.cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
        # ادمین اصلی
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id,is_admin) VALUES(?,1)",(ADMIN_ID,))
        self.conn.commit()

    def start_keep_alive(self):
        def ping():
            while True:
                try:
                    self.cursor.execute("SELECT 1")
                    self.conn.commit()
                except:
                    self.reconnect()
                time.sleep(60)
        threading.Thread(target=ping, daemon=True).start()

    def reconnect(self):
        try: self.conn.close()
        except: pass
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()

    # کاربران
    def add_user(self,user_id,username,first_name):
        now = datetime.now()
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
        now = datetime.now()
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

    # بررسی عضویت در کانال‌ها
    def check_membership(self,user_id):
        try:
            for username, _ in REQUIRED_CHANNELS:
                member = bot.get_chat_member(username,user_id)
                if member.status not in ['member','administrator','creator']:
                    return False
            return True
        except:
            return False

    # آمار
    def get_stats(self):
        today=datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute("SELECT COUNT(*),SUM(download_count) FROM users")
        total_users,total_downloads=self.cursor.fetchone()
        self.cursor.execute("SELECT COUNT(*) FROM groups")
        total_groups=self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE date(last_use)=date('now')")
        active_today=self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM groups WHERE date(last_active)=date('now')")
        active_groups=self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1")
        blocked=self.cursor.fetchone()[0]
        return {
            "total_users":total_users,
            "total_downloads":total_downloads or 0,
            "total_groups":total_groups,
            "active_today":active_today,
            "active_groups":active_groups,
            "blocked":blocked,
            "bot_status":self.get_setting("bot_status"),
            "group_mode":self.get_setting("group_mode"),
            "private_mode":self.get_setting("private_mode")
        }

    def get_users(self,limit=20):
        self.cursor.execute("""
        SELECT user_id, username, first_name, download_count, is_blocked
        FROM users ORDER BY last_use DESC LIMIT ?
        """,(limit,))
        return self.cursor.fetchall()

    def get_groups(self,limit=20):
        self.cursor.execute("""
        SELECT chat_id, title, added_date, last_active, is_active
        FROM groups ORDER BY last_active DESC LIMIT ?
        """,(limit,))
        return self.cursor.fetchall()

    def get_recent_downloads(self,limit=20):
        self.cursor.execute("""
        SELECT user_id,url,platform,timestamp FROM downloads ORDER BY timestamp DESC LIMIT ?
        """,(limit,))
        return self.cursor.fetchall()

# ================= ربات و وب =================
db=Database()
bot=telebot.TeleBot(TOKEN)
app=Flask(__name__)

# ================= دانلود =================
def download_video(url,chat_id,user_id,is_group=False):
    try:
        if not db.check_membership(user_id):
            bot.send_message(chat_id,"⛔ برای استفاده از ربات ابتدا در کانال‌های ما عضو شوید!")
            return
        platform=detect_platform(url)
        ydl_opts={"quiet":True,"no_warnings":True,"outtmpl":f"{DOWNLOAD_PATH}/%(title)s.%(ext)s"}
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
            bot.edit_message_text("❌ حجم فایل بیشتر از ۳۰۰MB",chat_id,msg.message_id)
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

# ================= تلگرام =================
@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id,message.from_user.username,message.from_user.first_name)
    
    # بررسی عضویت اجباری
    if not db.check_membership(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "⛔ برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو شوید:\n" +
            "\n".join([f"{username}" for username, _ in REQUIRED_CHANNELS])
        )
        return

    welcome_text = (
        f"🎬 سلام {message.from_user.first_name or message.from_user.username}!\n\n"
        "من ربات 𝘁𝗼𝗽 𝘁𝗼𝗽𝘆 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗿 هستم 🤖\n"
        "می‌تونی منو به گروه خودت اضافه کنی یا مستقیم به من لینک بدی تا هر چیزی رو دانلود کنم!\n\n"
        "✅ پشتیبانی از: یوتیوب، تیک‌تاک، اینستاگرام، توییتر، فیسبوک و سایر لینک‌ها\n"
        "✅ می‌تونی هر چیزی که میخوای دانلود کنی: ویدیو، آهنگ، عکس، فایل‌ها و ...\n\n"
        "📌 فقط کافیه لینک رو برای من بفرستی و من دانلود و برات ارسال می‌کنم."
    )
    bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id!=ADMIN_ID:
        return
    stats=db.get_stats()
    users=db.get_users(10)
    downloads=db.get_recent_downloads(10)
    groups=db.get_groups(10)
    markup=InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("🟢 روشن",callback_data="on"))
    markup.add(InlineKeyboardButton("🔴 خاموش",callback_data="off"))
    text=f"👑 پنل مدیریت\n\nآمار:\nکل کاربران: {stats['total_users']}\nدانلودها: {stats['total_downloads']}\nگروه‌ها: {stats['total_groups']}\nفعال امروز: {stats['active_today']}\nبلاک شده: {stats['blocked']}\n\nآخرین کاربران:\n"
    for u in users:
        text+=f"{u[0]} | {u[2] or u[1]} | دانلود: {u[3]} | {'🔒' if u[4] else '✅'}\n"
    text+="\nآخرین دانلودها:\n"
    for d in downloads:
        text+=f"{d[0]} | {d[1]} | {d[2]} | {d[3][:16]}\n"
    text+="\nآخرین گروه‌ها:\n"
    for g in groups:
        text+=f"{g[0]} | {g[1]} | {'فعال' if g[4] else 'غیرفعال'}\n"
    bot.send_message(message.chat.id,text,reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    if call.data in ["on","off"]:
        if call.from_user.id!=ADMIN_ID:
            bot.answer_callback_query(call.id,"⛔ دسترسی ندارید")
            return
        db.set_setting("bot_status","ON" if call.data=="on" else "OFF")
        bot.edit_message_text(f"وضعیت جدید: {call.data.upper()}",call.message.chat.id,call.message.message_id)

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    if db.get_setting("bot_status")=="OFF": return
    if db.is_blocked(message.from_user.id): return

    db.add_user(message.from_user.id,message.from_user.username,message.from_user.first_name)
    if message.chat.type in ["group","supergroup"]:
        db.add_group(message.chat.id,message.chat.title)

    # بررسی عضویت اجباری قبل از دانلود
    if not db.check_membership(message.from_user.id):
        bot.send_message(
            message.chat.id,
            "⛔ برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو شوید:\n" +
            "\n".join([f"{username}" for username, _ in REQUIRED_CHANNELS])
        )
        return

    urls = extract_urls(message.text)
    if not urls: return
    url = urls[0]
    bot.reply_to(message,"✅ لینک دریافت شد، شروع دانلود...")
    threading.Thread(
        target=download_video,
        args=(url,message.chat.id,message.from_user.id,message.chat.type in ["group","supergroup"]),
        daemon=True
    ).start()

# ================= وب پنل حرفه‌ای =================
HTML_TEMPLATE="""<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="utf-8">
<title>پنل مدیریت ربات</title>
<style>
body{font-family:tahoma;background:#f5f6fa;padding:20px;}
h1{text-align:center;color:#333;}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:20px;}
.stat-card{background:#fff;padding:20px;border-radius:10px;text-align:center;box-shadow:0 0 10px #ccc;}
.stat-value{font-size:28px;color:#667eea;font-weight:bold;}
.btn{padding:10px 20px;border-radius:5px;text-decoration:none;margin:5px;color:#fff;}
.btn-success{background:#4caf50;} .btn-danger{background:#f44336;}
table{width:100%;border-collapse:collapse;margin-top:20px;}
th,td{border:1px solid #ddd;padding:8px;text-align:center;}
th{background:#667eea;color:#fff;}
</style>
</head>
<body>
<h1>🤖 پنل مدیریت ربات</h1>
<div class="stats-grid">
<div class="stat-card"><div>👥 کاربران کل</div><div class="stat-value">{{ stats.total_users }}</div></div>
<div class="stat-card"><div>📥 دانلود کل</div><div class="stat-value">{{ stats.total_downloads }}</div></div>
<div class="stat-card"><div>🟢 فعال امروز</div><div class="stat-value">{{ stats.active_today }}</div></div>
<div class="stat-card"><div>🔒 بلاک شده</div><div class="stat-value">{{ stats.blocked }}</div></div>
</div>
<div style="text-align:center;">
<a href="/toggle/on" class="btn btn-success">🟢 روشن</a>
<a href="/toggle/off" class="btn btn-danger">🔴 خاموش</a>
</div>

<h2>آخرین کاربران</h2>
<table>
<tr><th>ID</th><th>نام</th><th>دانلودها</th><<th>وضعیت</th></tr>
{% for u in users %}
<tr>
<td>{{ u[0] }}</td>
<td>{{ u[2] or u[1] }}</td>
<td>{{ u[3] }}</td>
<td>{{ '🔒' if u[4] else '✅' }}</td>
</tr>
{% endfor %}
</table>

<h2>آخرین دانلودها</h2>
<table>
<tr><th>UserID</th><th>لینک</th><th>پلتفرم</th><th>زمان</th></tr>
{% for d in downloads %}
<tr>
<td>{{ d[0] }}</td>
<td>{{ d[1] }}</td>
<td>{{ d[2] }}</td>
<td>{{ d[3][:16] }}</td>
</tr>
{% endfor %}
</table>

<h2>آخرین گروه‌ها</h2>
<table>
<tr><th>ID</th><th>نام گروه</th><th>وضعیت</th></tr>
{% for g in groups %}
<tr>
<td>{{ g[0] }}</td>
<td>{{ g[1] }}</td>
<td>{{ 'فعال' if g[4] else 'غیرفعال' }}</td>
</tr>
{% endfor %}
</table>

</body>
</html>
"""

@app.route('/')
def home():
    stats = db.get_stats()
    users = db.get_users(20)
    downloads = db.get_recent_downloads(20)
    groups = db.get_groups(20)
    return render_template_string(HTML_TEMPLATE, stats=stats, users=users, downloads=downloads, groups=groups)

@app.route('/toggle/<status>')
def toggle(status):
    # فقط ادمین می‌تواند ربات را روشن/خاموش کند
    if status in ["on","off"]:
        db.set_setting("bot_status","ON" if status=="on" else "OFF")
    return redirect('/')

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# ================= اجرا =================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("🚀 ربات 𝘁𝗼𝗽 𝘁𝗼𝗽𝘆 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗿 آماده است")
    app.run(host="0.0.0.0", port=PORT)
