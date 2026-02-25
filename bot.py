# -*- coding: utf-8 -*-
import os
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request
import telebot
import yt_dlp
import sqlite3

# ================= تنظیمات ساده =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 300 * 1024 * 1024  # 300 مگابایت
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get('PORT', 8080))

# ================= آماده‌سازی =================
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= دیتابیس خیلی ساده =================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, blocked INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS stats (id INTEGER PRIMARY KEY, total INTEGER DEFAULT 0)")
cursor.execute("INSERT OR IGNORE INTO stats (id, total) VALUES (1, 0)")
conn.commit()

# ================= تابع دانلود =================
def download_video(url, chat_id):
    try:
        # تنظیمات ساده برای همه سایت‌ها
        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'format': 'best[filesize<300M]',
            'ignoreerrors': True,
        }
        
        bot.send_message(chat_id, "⏳ دارم دانلود میکنم...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # اگه فایل mp3 خواسته باشیم
            if 'mp3' in url.lower() or 'audio' in url.lower():
                ydl_opts = {
                    'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
                    'quiet': True,
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                    }],
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                    info = ydl2.extract_info(url, download=True)
                    filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
            
            # ارسال فایل
            if os.path.exists(filename):
                with open(filename, 'rb') as f:
                    if filename.endswith('.mp3'):
                        bot.send_audio(chat_id, f, caption="🎵 دانلود شد")
                    elif filename.endswith(('.mp4', '.mkv')):
                        bot.send_video(chat_id, f, caption="🎬 دانلود شد")
                    elif filename.endswith(('.jpg', '.png', '.gif')):
                        bot.send_photo(chat_id, f, caption="🖼️ دانلود شد")
                    else:
                        bot.send_document(chat_id, f, caption="📄 دانلود شد")
                
                # آپدیت آمار
                cursor.execute("UPDATE stats SET total = total + 1 WHERE id = 1")
                conn.commit()
                
                # پاک کردن فایل
                os.remove(filename)
            else:
                bot.send_message(chat_id, "❌ فایل پیدا نشد")
                
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطا: {str(e)[:100]}")

# ================= دستورات ربات =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    
    welcome = """
🎬 **ربات دانلود از همه سایت‌ها**

🔹 لینک بفرست تا خودم تشخیص بدم چی هست
🔹 یوتیوب، اینستاگرام، تیک‌تاک، توییتر، هر چی
🔹 حجم تا ۳۰۰ مگابایت

✅ فقط لینک رو بفرست، بقیه با من
    """
    bot.reply_to(message, welcome, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT total FROM stats WHERE id = 1")
    downloads = cursor.fetchone()[0]
    
    text = f"""
👑 **پنل ادمین**
👥 کاربران: {users}
📥 دانلودها: {downloads}
    """
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    url = message.text.strip()
    user_id = message.from_user.id
    
    # بررسی بلاک بودن
    cursor.execute("SELECT blocked FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result and result[0] == 1:
        bot.reply_to(message, "⛔ شما بلاک هستید")
        return
    
    # بررسی لینک
    if not url.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ لینک معتبر بفرست")
        return
    
    # شروع دانلود در thread جدا
    threading.Thread(target=download_video, args=(url, message.chat.id)).start()
    bot.reply_to(message, "✅ لینک دریافت شد، دانلود شروع شد")

# ================= Webhook =================
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

@app.route('/')
def home():
    return "ربات فعال است 🚀"

# ================= شروع =================
if __name__ == "__main__":
    # تنظیم webhook
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("✅ Webhook تنظیم شد")
    print(f"🚀 ربات روی پورت {PORT} اجرا شد")
    
    # اجرا
    app.run(host='0.0.0.0', port=PORT)
