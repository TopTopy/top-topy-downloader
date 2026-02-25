# -*- coding: utf-8 -*-
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from flask import Flask, request, redirect, render_template_string
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3
import sys
import signal
import re

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 300 * 1024 * 1024  # 300 مگابایت
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get('PORT', 8080))

# ================= آماده‌سازی =================
os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= دیتابیس =================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_database()
        self.start_keep_alive()
    
    def init_database(self):
        # جدول کاربران
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
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
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_date TIMESTAMP,
            last_active TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """)
        
        # جدول آمار
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            downloads INTEGER DEFAULT 0,
            users INTEGER DEFAULT 0,
            groups INTEGER DEFAULT 0
        )
        """)
        
        # جدول تنظیمات
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        
        # جدول دانلودها
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
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
        
        # تنظیمات پیش‌فرض
        default_settings = [
            ('bot_status', 'ON'),
            ('total_downloads', '0'),
            ('total_users', '0'),
            ('total_groups', '0'),
            ('group_mode', 'ON'),
            ('private_mode', 'ON'),
            ('last_reset', str(datetime.now().date())),
            ('created_at', str(datetime.now()))
        ]
        
        for key, value in default_settings:
            self.cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        
        # ادمین اصلی
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, 1)", (ADMIN_ID,))
        
        self.conn.commit()
        print("✅ دیتابیس راه‌اندازی شد")
    
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
        try:
            self.conn.close()
        except:
            pass
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
    
    def add_user(self, user_id, username=None, first_name=None):
        now = datetime.now()
        date = now.strftime('%Y-%m-%d')
        
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = self.cursor.fetchone()
        
        if user:
            self.cursor.execute("UPDATE users SET last_use = ?, username = ?, first_name = ? WHERE user_id = ?",
                              (now, username, first_name, user_id))
        else:
            self.cursor.execute("""
                INSERT INTO users (user_id, username, first_name, joined_date, last_use, download_count, is_blocked, is_admin)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0)
            """, (user_id, username, first_name, now, now))
            
            self.cursor.execute("""
                INSERT INTO stats (date, users) VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET users = users + 1
            """, (date,))
            
            total = self.get_setting('total_users')
            self.set_setting('total_users', str(int(total) + 1))
        
        self.conn.commit()
    
    def add_group(self, chat_id, title):
        now = datetime.now()
        date = now.strftime('%Y-%m-%d')
        
        self.cursor.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        group = self.cursor.fetchone()
        
        if group:
            self.cursor.execute("UPDATE groups SET last_active = ?, title = ? WHERE chat_id = ?", (now, title, chat_id))
        else:
            self.cursor.execute("""
                INSERT INTO groups (chat_id, title, added_date, last_active, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (chat_id, title, now, now))
            
            self.cursor.execute("""
                INSERT INTO stats (date, groups) VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET groups = groups + 1
            """, (date,))
            
            total = self.get_setting('total_groups')
            self.set_setting('total_groups', str(int(total) + 1))
        
        self.conn.commit()
    
    def add_download(self, user_id, chat_id, url, format_type, size, source='private', platform='unknown'):
        now = datetime.now()
        date = now.strftime('%Y-%m-%d')
        
        self.cursor.execute("""
            INSERT INTO downloads (user_id, chat_id, url, format, size, timestamp, source, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, chat_id, url, format_type, size, now, source, platform))
        
        self.cursor.execute("UPDATE users SET download_count = download_count + 1, last_use = ? WHERE user_id = ?", (now, user_id))
        
        self.cursor.execute("""
            INSERT INTO stats (date, downloads) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET downloads = downloads + 1
        """, (date,))
        
        total = self.get_setting('total_downloads')
        self.set_setting('total_downloads', str(int(total) + 1))
        
        self.conn.commit()
    
    def get_setting(self, key):
        self.cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = self.cursor.fetchone()
        return result[0] if result else '0'
    
    def set_setting(self, key, value):
        self.cursor.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
        self.conn.commit()
    
    def get_stats(self):
        today = datetime.now().strftime('%Y-%m-%d')
        
        self.cursor.execute("SELECT downloads, users, groups FROM stats WHERE date = ?", (today,))
        today_stats = self.cursor.fetchone()
        today_downloads = today_stats[0] if today_stats else 0
        today_users = today_stats[1] if today_stats else 0
        today_groups = today_stats[2] if today_stats else 0
        
        total_users = self.get_setting('total_users')
        total_downloads = self.get_setting('total_downloads')
        total_groups = self.get_setting('total_groups')
        
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE date(last_use) = date('now')")
        active_today = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM groups WHERE date(last_active) = date('now')")
        active_groups = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
        blocked = self.cursor.fetchone()[0]
        
        bot_status = self.get_setting('bot_status')
        group_mode = self.get_setting('group_mode')
        private_mode = self.get_setting('private_mode')
        
        return {
            'total_users': int(total_users),
            'total_downloads': int(total_downloads),
            'total_groups': int(total_groups),
            'today_users': today_users,
            'today_downloads': today_downloads,
            'today_groups': today_groups,
            'active_today': active_today,
            'active_groups': active_groups,
            'blocked': blocked,
            'bot_status': bot_status,
            'group_mode': group_mode,
            'private_mode': private_mode
        }
    
    def get_users(self, limit=20):
        self.cursor.execute("""
            SELECT user_id, username, first_name, joined_date, last_use, download_count, is_blocked, is_admin
            FROM users ORDER BY last_use DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()
    
    def get_groups(self, limit=20):
        self.cursor.execute("""
            SELECT chat_id, title, added_date, last_active, is_active
            FROM groups ORDER BY last_active DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()
    
    def get_recent_downloads(self, limit=10):
        self.cursor.execute("""
            SELECT d.*, u.username, u.first_name, g.title
            FROM downloads d
            LEFT JOIN users u ON d.user_id = u.user_id
            LEFT JOIN groups g ON d.chat_id = g.chat_id
            ORDER BY d.timestamp DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()
    
    def block_user(self, user_id):
        self.cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()
    
    def unblock_user(self, user_id):
        self.cursor.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (user_id,))
        self.conn.commit()
    
    def is_blocked(self, user_id):
        self.cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result and result[0] == 1
    
    def toggle_group_mode(self):
        current = self.get_setting('group_mode')
        new = 'OFF' if current == 'ON' else 'ON'
        self.set_setting('group_mode', new)
        return new
    
    def toggle_private_mode(self):
        current = self.get_setting('private_mode')
        new = 'OFF' if current == 'ON' else 'ON'
        self.set_setting('private_mode', new)
        return new
    
    def reset_stats(self):
        today = datetime.now().strftime('%Y-%m-%d')
        self.set_setting('total_downloads', '0')
        self.set_setting('total_users', '0')
        self.set_setting('total_groups', '0')
        self.cursor.execute("DELETE FROM downloads")
        self.cursor.execute("DELETE FROM stats")
        self.conn.commit()

# ================= ایجاد دیتابیس =================
db = Database()

# ================= راه‌اندازی ربات =================
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= تابع تشخیص لینک =================
def extract_urls(text):
    url_pattern = re.compile(r'https?://[^\s]+')
    return url_pattern.findall(text)

# ================= تشخیص پلتفرم =================
def detect_platform(url):
    url_lower = url.lower()
    if 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    elif 'instagram.com' in url_lower:
        return 'instagram'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'twitter'
    elif 'facebook.com' in url_lower or 'fb.com' in url_lower:
        return 'facebook'
    else:
        return 'other'

# ================= تابع دانلود =================
def download_video(url, chat_id, user_id, message_obj, is_group=False):
    try:
        platform = detect_platform(url)
        is_audio = any(word in url.lower() for word in ['mp3', 'audio', 'music', 'sound'])
        
        # تنظیمات پایه
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
        }
        
        # تنظیمات بر اساس پلتفرم
        if platform == 'tiktok':
            ydl_opts['headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
            }
        
        if is_audio:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts.update({
                'format': 'best[filesize<300M]',
            })
        
        msg = bot.send_message(chat_id, f"⏳ **در حال دانلود از {platform}...**", parse_mode="Markdown")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                bot.edit_message_text("❌ **خطا در دریافت اطلاعات**", chat_id, msg.message_id, parse_mode="Markdown")
                return
            
            title = info.get('title', 'فایل')
            extractor = info.get('extractor', platform)
            
            # پیدا کردن فایل
            filename = None
            if is_audio:
                filename = f"{DOWNLOAD_PATH}/{title}.mp3"
            else:
                filename = ydl.prepare_filename(info)
                
                if not filename or not os.path.exists(filename):
                    for f in os.listdir(DOWNLOAD_PATH):
                        if title in f:
                            filename = os.path.join(DOWNLOAD_PATH, f)
                            break
            
            if filename and os.path.exists(filename):
                size = os.path.getsize(filename)
                
                if size <= MAX_FILE_SIZE:
                    bot.edit_message_text("📤 **در حال آپلود...**", chat_id, msg.message_id, parse_mode="Markdown")
                    
                    caption = f"✅ **دانلود شد**\n📌 **عنوان:** {title}\n🌐 **منبع:** {extractor}"
                    
                    with open(filename, 'rb') as f:
                        if is_audio or filename.endswith('.mp3'):
                            bot.send_audio(chat_id, f, caption=caption, parse_mode="Markdown")
                        elif filename.endswith(('.mp4', '.mkv', '.webm')):
                            bot.send_video(chat_id, f, caption=caption, parse_mode="Markdown")
                        elif filename.endswith(('.jpg', '.png', '.gif')):
                            bot.send_photo(chat_id, f, caption=caption, parse_mode="Markdown")
                        else:
                            bot.send_document(chat_id, f, caption=caption, parse_mode="Markdown")
                    
                    # ثبت آمار
                    source = 'group' if is_group else 'private'
                    db.add_download(user_id, chat_id, url, 'audio' if is_audio else 'video', size, source, platform)
                    
                    bot.delete_message(chat_id, msg.message_id)
                else:
                    bot.edit_message_text("❌ **حجم فایل بیش از ۳۰۰ مگابایت است**", chat_id, msg.message_id, parse_mode="Markdown")
                
                try:
                    os.remove(filename)
                except:
                    pass
            else:
                bot.edit_message_text("❌ **فایل پیدا نشد**", chat_id, msg.message_id, parse_mode="Markdown")
    
    except Exception as e:
        error_msg = f"❌ **خطا در دانلود:**\n`{str(e)[:100]}`"
        bot.send_message(chat_id, error_msg, parse_mode="Markdown")

# ================= طراحی پیام خوش‌آمدگویی =================
WELCOME_MESSAGE = """
╔══════════════════════════╗
║    🎬 **ربات دانلود حرفه‌ای**    ║
╚══════════════════════════╝

✨ **قابلیت‌های ویژه:**
━━━━━━━━━━━━━━━━━━
📥 **دانلود از تمام سایت‌ها**
• ✅ یوتیوب | اینستاگرام | تیک‌تاک
• ✅ توییتر | فیسبوک | پینترست
• ✅ و بیش از ۱۰۰۰ سایت دیگر

🎯 **نحوه استفاده:**
━━━━━━━━━━━━━━━━━━
✅ فقط کافیه لینک رو بفرستی
✅ ربات خودش تشخیص میده چه فرمتی باشه
✅ حجم مجاز: ۳۰۰ مگابایت

🌟 **توسط:** @top_topy_downloader
📢 **کانال:** @IdTOP_TOPY
"""

HELP_MESSAGE = """
╔══════════════════════════╗
║        📚 **راهنما**        ║
╚══════════════════════════╝

🔰 **دستورات پایه:**
━━━━━━━━━━━━━━━━━━
/start - شروع ربات
/help - راهنما
/admin - پنل مدیریت (فقط ادمین)

💡 **مثال‌ها:**
━━━━━━━━━━━━━━━━━━
🔹 ویدیو یوتیوب:
   https://youtube.com/...
   
🔹 ویدیو تیک‌تاک:
   https://tiktok.com/...
   
🔹 پست اینستاگرام:
   https://instagram.com/...
"""

# ================= دستورات ربات =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    db.add_user(user_id, username, first_name)
    
    # طراحی دکمه‌ها
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📚 راهنما", callback_data="help"),
        InlineKeyboardButton("📢 کانال", url="https://t.me/IdTOP_TOPY"),
        InlineKeyboardButton("👨‍💻 ادمین", url=f"tg://user?id={ADMIN_ID}"),
    )
    
    bot.reply_to(message, WELCOME_MESSAGE, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def help_command(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_start"))
    bot.reply_to(message, HELP_MESSAGE, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 روشن" if stats['bot_status'] == 'OFF' else "🟢 روشن ✅", callback_data="toggle_on"),
        InlineKeyboardButton("🔴 خاموش" if stats['bot_status'] == 'ON' else "🔴 خاموش ✅", callback_data="toggle_off"),
        InlineKeyboardButton("📊 آمار", callback_data="show_stats"),
        InlineKeyboardButton("👥 کاربران", callback_data="show_users"),
        InlineKeyboardButton("📥 دانلودها", callback_data="show_downloads"),
    )
    
    text = f"""
👑 **پنل مدیریت**

📊 **آمار کلی:**
👥 کاربران: {stats['total_users']}
📥 دانلودها: {stats['total_downloads']}
📊 امروز: {stats['today_downloads']}

🟢 وضعیت: {'روشن ✅' if stats['bot_status'] == 'ON' else 'خاموش ❌'}
    """
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "back_to_start":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📚 راهنما", callback_data="help"),
            InlineKeyboardButton("📢 کانال", url="https://t.me/IdTOP_TOPY"),
            InlineKeyboardButton("👨‍💻 ادمین", url=f"tg://user?id={ADMIN_ID}"),
        )
        bot.edit_message_text(WELCOME_MESSAGE, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "help":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_start"))
        bot.edit_message_text(HELP_MESSAGE, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    # بخش ادمین
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید")
        return
    
    if call.data == "toggle_on":
        db.set_setting('bot_status', 'ON')
        bot.answer_callback_query(call.id, "✅ ربات روشن شد")
        bot.edit_message_text("✅ ربات روشن شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "toggle_off":
        db.set_setting('bot_status', 'OFF')
        bot.answer_callback_query(call.id, "✅ ربات خاموش شد")
        bot.edit_message_text("✅ ربات خاموش شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "show_stats":
        stats = db.get_stats()
        text = f"""
📊 **آمار کامل**

👥 کاربران کل: {stats['total_users']}
👥 گروه‌ها: {stats['total_groups']}
📥 دانلود کل: {stats['total_downloads']}
📊 دانلود امروز: {stats['today_downloads']}
🟢 فعال امروز: {stats['active_today']}
🔒 بلاک شده: {stats['blocked']}
        """
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "show_users":
        users = db.get_users(10)
        text = "👥 **۱۰ کاربر آخر:**\n\n"
        for u in users:
            status = "🔒" if u[6] else "✅"
            name = u[2] or u[1] or 'ناشناس'
            text += f"{status} `{u[0]}` | {name} | دانلود: {u[5]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "show_downloads":
        downloads = db.get_recent_downloads(10)
        text = "📥 **۱۰ دانلود آخر:**\n\n"
        for d in downloads:
            name = d[8] or d[9] or 'ناشناس'
            text += f"• {name} | {d[3]} | {d[11]} | {d[6][:16]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ================= پردازش پیام‌ها =================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip()
    
    # ذخیره کاربر
    db.add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    # اگه گروه هست، ذخیره گروه
    if message.chat.type in ['group', 'supergroup']:
        db.add_group(chat_id, message.chat.title)
    
    # بررسی بلاک بودن
    if db.is_blocked(user_id):
        return
    
    # بررسی روشن بودن ربات
    if db.get_setting('bot_status') == 'OFF':
        if message.chat.type == 'private':
            bot.reply_to(message, "⛔ ربات خاموش است")
        return
    
    # بررسی لینک
    if not text.startswith(('http://', 'https://')):
        return
    
    # شروع دانلود
    bot.reply_to(message, "✅ **لینک دریافت شد، دانلود شروع شد...**", parse_mode="Markdown")
    is_group = message.chat.type in ['group', 'supergroup']
    threading.Thread(target=download_video, args=(text, chat_id, user_id, message, is_group)).start()

# ================= پنل وب =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <title>پنل مدیریت ربات</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: Tahoma, Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 20px;
            text-align: center;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
        }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            margin: 5px;
        }
        .btn-success { background: #4caf50; color: white; }
        .btn-danger { background: #f44336; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 پنل مدیریت ربات</h1>
            <p>وضعیت: {{ '🟢 روشن' if stats.bot_status == 'ON' else '🔴 خاموش' }}</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div>👥 کاربران</div>
                <div class="stat-value">{{ stats.total_users }}</div>
            </div>
            <div class="stat-card">
                <div>📥 دانلود کل</div>
                <div class="stat-value">{{ stats.total_downloads }}</div>
            </div>
            <div class="stat-card">
                <div>📊 امروز</div>
                <div class="stat-value">{{ stats.today_downloads }}</div>
            </div>
        </div>
        
        <div style="text-align: center;">
            <a href="/toggle/on" class="btn btn-success">🟢 روشن</a>
            <a href="/toggle/off" class="btn btn-danger">🔴 خاموش</a>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    stats = db.get_stats()
    return render_template_string(HTML_TEMPLATE, stats=stats)

@app.route('/toggle/<status>')
def toggle(status):
    if status in ['on', 'off']:
        db.set_setting('bot_status', 'ON' if status == 'on' else 'OFF')
    return redirect('/')

# ================= Webhook =================
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# ================= راه‌اندازی =================
if __name__ == "__main__":
    print("""
╔══════════════════════════╗
║   🚀 راه‌اندازی ربات...   ║
╚══════════════════════════╝
    """)
    
    # تنظیم webhook
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("✅ Webhook تنظیم شد")
    print(f"✅ پورت: {PORT}")
    print("✅ ربات آماده است!")
    
    # اجرای Flask
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
