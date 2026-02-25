# -*- coding: utf-8 -*-
import os
import threading
from queue import Queue
from datetime import datetime
import sqlite3
from flask import Flask, request, redirect
import yt_dlp
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from Crypto.Cipher import AES
import base64

# ================= کلید AES =================
SECRET_KEY = b"16bytesecretkey!"  # 16 بایت کلید

# ================= توکن و ادمین هش شده =================
ENCODED_TOKEN = "s4u4OyNNf5uZQO/5jhBmlb3/KD7VpHTlCFe9gD57Rfo="  # هش شده توکن واقعی
ENCODED_ADMIN = "ODIyNjA5MTI5Mg=="  # هش شده ایدی ادمین

def decrypt_aes(enc_str):
    cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
    decoded = base64.b64decode(enc_str)
    decrypted = cipher.decrypt(decoded)
    return decrypted.rstrip(b"\0").decode()

TOKEN = decrypt_aes(ENCODED_TOKEN)
ADMIN_ID = int(decrypt_aes(ENCODED_ADMIN))

# ================= تنظیمات =================
MAX_FILE_SIZE = 300 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://YOUR_DOMAIN_OR_NGROK/webhook"  # HTTPS الزامیست

bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

# ================= دیتابیس =================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    blocked INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS stats (
    total_downloads INTEGER DEFAULT 0,
    today_downloads INTEGER DEFAULT 0,
    last_date TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    bot_status TEXT
)
""")
cursor.execute("SELECT COUNT(*) FROM settings")
if cursor.fetchone()[0] == 0:
    cursor.execute("INSERT INTO settings VALUES ('ON')")
    cursor.execute("INSERT INTO stats VALUES (0,0,?)", (str(datetime.now().date()),))
conn.commit()

# ================= صف دانلود =================
download_queue = Queue()
def worker():
    while True:
        call, url, fmt = download_queue.get()
        process_download(call, url, fmt)
        download_queue.task_done()

for _ in range(2):
    threading.Thread(target=worker, daemon=True).start()

# ================= توابع کمکی =================
def is_bot_on():
    cursor.execute("SELECT bot_status FROM settings")
    return cursor.fetchone()[0] == "ON"

def add_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (user_id,))
    conn.commit()

def update_stats():
    today = str(datetime.now().date())
    cursor.execute("SELECT total_downloads, today_downloads, last_date FROM stats")
    total, today_count, last_date = cursor.fetchone()
    if last_date != today:
        today_count = 0
    cursor.execute("UPDATE stats SET total_downloads=?, today_downloads=?, last_date=?",
                   (total+1, today_count+1, today))
    conn.commit()

# ================= دانلود =================
def process_download(call, url, fmt):
    chat_id = call.message.chat.id
    cursor.execute("SELECT blocked FROM users WHERE user_id=?", (call.from_user.id,))
    blocked = cursor.fetchone()[0]
    if blocked:
        bot.send_message(chat_id, "⛔ شما بلاک هستید.")
        return
    if not is_bot_on():
        bot.send_message(chat_id, "⛔ ربات خاموش است.")
        return
    bot.send_message(chat_id, "⏳ در حال دانلود...")
    try:
        if fmt == "mp3":
            ydl_opts = {
                'format': 'bestaudio',
                'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
                'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec':'mp3'}],
                'quiet': True
            }
        else:
            ydl_opts = {
                'format': fmt,
                'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
                'quiet': True
            }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
        if os.path.exists(file_path):
            if os.path.getsize(file_path) <= MAX_FILE_SIZE:
                with open(file_path, "rb") as f:
                    bot.send_document(chat_id, f)
                update_stats()
            else:
                bot.send_message(chat_id, "❌ فایل بیشتر از ۳۰۰MB است.")
            os.remove(file_path)
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطا:\n{e}")

# ================= دستورات =================
@bot.message_handler(commands=['start'])
def start(message):
    add_user(message.from_user.id)
    bot.reply_to(message, "👋 لینک رو بفرست.")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🟢 روشن", callback_data="on"),
        InlineKeyboardButton("🔴 خاموش", callback_data="off"),
        InlineKeyboardButton("📊 آمار", callback_data="stats"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="broadcast"),
        InlineKeyboardButton("🔒 بلاک/آن‌بلاک", callback_data="block")
    )
    bot.send_message(message.chat.id, "👑 پنل مدیریت", reply_markup=markup)

# =================== Flask Dashboard =================
app = Flask(__name__)

@app.route('/')
def dashboard():
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT total_downloads, today_downloads FROM stats")
    total, today = cursor.fetchone()
    cursor.execute("SELECT bot_status FROM settings")
    status = cursor.fetchone()[0]
    return f"""
    <h2>پنل ادمین</h2>
    <p>وضعیت ربات: {status}</p>
    <p>تعداد کاربران: {users}</p>
    <p>کل دانلودها: {total}</p>
    <p>دانلود امروز: {today}</p>
    <form method="POST" action="/toggle">
        <button name="action" value="on">روشن</button>
        <button name="action" value="off">خاموش</button>
    </form>
    <form method="POST" action="/broadcast">
        <input name="message" placeholder="پیام همگانی">
        <button>ارسال پیام</button>
    </form>
    <form method="POST" action="/reset_stats">
        <button>ریست آمار</button>
    </form>
    """

@app.route('/toggle', methods=['POST'])
def toggle():
    action = request.form.get('action')
    cursor.execute("UPDATE settings SET bot_status=?", (action.upper(),))
    conn.commit()
    return redirect('/')

@app.route('/reset_stats', methods=['POST'])
def reset_stats():
    today = str(datetime.now().date())
    cursor.execute("UPDATE stats SET total_downloads=0, today_downloads=0, last_date=?", (today,))
    conn.commit()
    return redirect('/')

@app.route('/broadcast', methods=['POST'])
def broadcast():
    msg = request.form.get('message')
    cursor.execute("SELECT user_id, blocked FROM users")
    users = cursor.fetchall()
    for user_id, blocked in users:
        if not blocked:
            try:
                bot.send_message(user_id, msg)
            except:
                continue
    return redirect('/')

# =================== Webhook =================
@app.route(f'/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return '', 200

def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)

# =================== اجرا دائم =================
def run_bot():
    while True:
        try:
            set_webhook()
            app.run(host='0.0.0.0', port=5000)
        except Exception as e:
            print("❌ خطا، ری‌استارت مجدد:", e)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()