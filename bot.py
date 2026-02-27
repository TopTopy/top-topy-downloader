# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import subprocess
from datetime import datetime
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 300 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))
REQUIRED_CHANNELS = [
    ("@top_topy_downloader", "https://t.me/top_topy_downloader"),
    ("@IdTOP_TOPY", "https://t.me/IdTOP_TOPY")
]

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= بررسی نصب yt-dlp =================
def check_yt_dlp():
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ yt-dlp نسخه {result.stdout.strip()} نصب است")
            return True
    except:
        try:
            subprocess.run(['pip', 'install', '--upgrade', 'yt-dlp'], check=True)
            print("✅ yt-dlp نصب شد")
            return True
        except:
            print("❌ yt-dlp نصب نیست")
            return False

YT_DLP_OK = check_yt_dlp()

# ================= دیتابیس ساده =================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()

    def init_db(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TIMESTAMP,
            download_count INTEGER DEFAULT 0
        )
        """)
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (ADMIN_ID,))
        self.conn.commit()

    def add_user(self, user_id, username, first_name):
        now = datetime.now()
        self.cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE users SET username=?, first_name=?, last_use=? WHERE user_id=?", 
                              (username, first_name, now, user_id))
        else:
            self.cursor.execute("INSERT INTO users(user_id,username,first_name,joined_date) VALUES(?,?,?,?)",
                              (user_id, username, first_name, now))
        self.conn.commit()

    def add_download(self, user_id):
        self.cursor.execute("UPDATE users SET download_count=download_count+1 WHERE user_id=?", (user_id,))
        self.conn.commit()

# ================= ابزار لینک =================
def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url

def check_membership(user_id):
    try:
        for username, _ in REQUIRED_CHANNELS:
            member = bot.get_chat_member(username, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except:
        return False

def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

# ================= دانلود با Fallback Format =================
def download_video(url, quality):

    unique = str(int(time.time()*1000))
    output_template = os.path.join(DOWNLOAD_PATH, f"%(title)s_{unique}.%(ext)s")

    format_priority = {
        "best": [
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            "bestvideo+bestaudio/best",
            "best[ext=mp4]",
            "best"
        ],
        "720": [
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]",
            "best[height<=720][ext=mp4]",
            "best[height<=720]",
        ],
        "480": [
            "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]",
            "best[height<=480][ext=mp4]",
            "best[height<=480]",
        ],
        "360": [
            "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]",
            "best[height<=360][ext=mp4]",
            "best[height<=360]",
        ],
        "audio": [
            "bestaudio[ext=m4a]",
            "bestaudio"
        ]
    }

    formats = format_priority.get(quality, format_priority["best"])

    for fmt in formats:
        try:
            ydl_opts = {
                "format": fmt,
                "outtmpl": output_template,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 10,
                "fragment_retries": 10,
                "merge_output_format": "mp4",
                "socket_timeout": 30,
                "concurrent_fragment_downloads": 1,
                "restrictfilenames": True,
                "nocheckcertificate": True,
            }

            if quality == "audio":
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if "requested_downloads" in info and info["requested_downloads"]:
                    file_path = info["requested_downloads"][0]["filepath"]
                else:
                    file_path = ydl.prepare_filename(info)

                if quality == "audio":
                    file_path = os.path.splitext(file_path)[0] + ".mp3"

                if os.path.exists(file_path):
                    return file_path

        except Exception as e:
            print(f"⚠ فرمت {fmt} کار نکرد: {str(e)[:50]}")
            continue

    return None

# ================= کیبورد کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 بهترین", callback_data="q_best"),
        InlineKeyboardButton("720p", callback_data="q_720"),
        InlineKeyboardButton("480p", callback_data="q_480"),
        InlineKeyboardButton("360p", callback_data="q_360"),
        InlineKeyboardButton("🎵 صدا", callback_data="q_audio"),
        InlineKeyboardButton("❌ لغو", callback_data="q_cancel")
    )
    return markup

# ================= ایجاد نمونه =================
db = Database()
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = set()
lock = threading.Lock()

# ================= استارت =================
@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if not check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    bot.reply_to(
        message,
        "🎬 **ربات دانلود یوتیوب**\n\n"
        "✅ لینک یوتیوب رو بفرست\n"
        "✅ پشتیبانی از Shorts\n"
        "✅ حجم مجاز: ۳۰۰ مگابایت",
        parse_mode="Markdown"
    )

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"✅ ربات فعال است\n"
    text += f"📊 دانلودهای هم‌زمان: {len(active_downloads)}"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ================= بررسی عضویت =================
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ عضو نشده‌اید!", show_alert=True)

# ================= دریافت لینک =================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    user_id = message.from_user.id

    if not check_membership(user_id):
        bot.reply_to(
            message,
            "🔒 **لطفاً ابتدا در کانال‌ها عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    if user_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است...")
        return

    url = extract_url(message.text)
    if not url:
        return

    if not is_youtube(url):
        bot.reply_to(message, "❌ فقط لینک یوتیوب بفرست!")
        return

    user_links[user_id] = url
    bot.reply_to(message, "📥 **کیفیت رو انتخاب کن:**", reply_markup=quality_keyboard(), parse_mode="Markdown")

# ================= انتخاب کیفیت =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def quality_selected(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if call.data == "q_cancel":
        bot.edit_message_text("❌ لغو شد.", chat_id, call.message.message_id)
        return

    if user_id in active_downloads:
        bot.answer_callback_query(call.id, "⏳ صبر کن...")
        return

    quality = call.data.replace("q_", "")
    url = user_links.get(user_id)

    if not url:
        bot.answer_callback_query(call.id, "❌ خطا!")
        return

    bot.edit_message_text("⏳ **در حال دانلود...**", chat_id, call.message.message_id, parse_mode="Markdown")

    def process():
        try:
            with lock:
                active_downloads.add(user_id)

            file_path = download_video(url, quality)

            if not file_path or not os.path.exists(file_path):
                bot.send_message(chat_id, "❌ خطا در دانلود! چند دقیقه بعد تلاش کن.")
                return

            file_size = os.path.getsize(file_path)
            if file_size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f}MB است")
                os.remove(file_path)
                return

            with open(file_path, "rb") as f:
                if quality == "audio":
                    bot.send_audio(chat_id, f, timeout=180)
                else:
                    bot.send_video(chat_id, f, timeout=180)

            os.remove(file_path)
            db.add_download(user_id)

            try:
                bot.edit_message_text("✅ **دانلود شد!**", chat_id, call.message.message_id)
            except:
                pass

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")

        finally:
            with lock:
                active_downloads.discard(user_id)
            if user_id in user_links:
                del user_links[user_id]

    threading.Thread(target=process).start()

# ================= وبهوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "ربات فعال است"

if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود یوتیوب - نسخه نهایی")
    print("="*60)
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات فعال شد!")
    print("="*60)
    
    app.run(host="0.0.0.0", port=PORT)
