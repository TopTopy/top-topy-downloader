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
import subprocess

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

# ================= نصب curl_cffi (برای impersonate) =================
try:
    import curl_cffi
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    print("⚠️ curl_cffi نصب نیست. برای تیک‌تاک باید نصب بشه:")
    print("pip install curl_cffi")

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

# ================= تابع دانلود با پشتیبانی تیک‌تاک =================
def download_video(url, chat_id, user_id, message_obj=None, is_group=False):
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
        
        # تنظیمات مخصوص تیک‌تاک [citation:1][citation:5]
        if platform == 'tiktok':
            ydl_opts.update({
                'format': 'best[ext=mp4]',
                'extractor_args': {'tiktok': {'app_version': 'latest'}},
            })
            
            # اگر curl_cffi نصب باشه، impersonate فعال میشه [citation:5]
            if HAS_CURL_CFFI:
                ydl_opts.update({
                    'impersonate': 'chrome-131',
                    'extractor_args': {'tiktok': {'webpage_download': '1'}},
                })
            
            # اضافه کردن هدرهای مرورگر
            ydl_opts['headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        
        # تنظیمات مخصوص یوتیوب
        elif platform == 'youtube':
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
        
        # تنظیمات مخصوص اینستاگرام [citation:5]
        elif platform == 'instagram':
            ydl_opts['headers'] = {
                'Referer': 'https://www.instagram.com/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            if is_audio:
                ydl_opts['format'] = 'bestaudio/best'
            else:
                ydl_opts['format'] = 'best[filesize<300M]'
        
        # تنظیمات عمومی برای بقیه سایت‌ها
        else:
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
        
        msg = bot.send_message(chat_id, f"⏳ **در حال دانلود از {platform}...**\n🔗 لینک دریافت شد", parse_mode="Markdown")
        
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
    
    except yt_dlp.utils.UnsupportedError:
        error_msg = f"❌ **این سایت ({platform}) پشتیبانی نمیشه**"
        if message_obj:
            bot.reply_to(message_obj, error_msg, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, error_msg, parse_mode="Markdown")
    
    except Exception as e:
        error_msg = f"❌ **خطا در دانلود از {platform}:**\n`{str(e)[:100]}`"
        
        # پیام خطای اختصاصی برای تیک‌تاک
        if platform == 'tiktok' and 'impersonate' in str(e).lower():
            error_msg += "\n\n💡 **نکته:** برای تیک‌تاک نیاز به نصب `curl_cffi` دارید:\n`pip install curl_cffi`"
        
        if message_obj:
            bot.reply_to(message_obj, error_msg, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, error_msg, parse_mode="Markdown")

# ================= طراحی پیام خوش‌آمدگویی =================
WELCOME_MESSAGE = """
╔══════════════════════════╗
║    🎬 **ربات دانلود حرفه‌ای**    ║
╚══════════════════════════╝

✨ **قابلیت‌های ویژه:**
━━━━━━━━━━━━━━━━━━
📥 **دانلود از تمام سایت‌ها**
• ✅ یوتیوب | اینستاگرام | توییتر
• ✅ تیک‌تاک | فیسبوک | پینترست
• ✅ و بیش از ۱۰۰۰ سایت دیگر

🎯 **امکانات ربات:**
• 🎵 دانلود صوتی با کیفیت بالا
• 🎬 دانلود ویدیو با کیفیت اصلی
• 🖼️ دانلود عکس و گیف

📊 **محدودیت‌ها:**
• ⬆️ حجم مجاز: ۳۰۰ مگابایت
• ⚡ سرعت بالا و بدون محدودیت

🤖 **نحوه استفاده:**
━━━━━━━━━━━━━━━━━━
✅ **در گروه‌ها:**
   فقط لینک رو بفرستید

✅ **در پیوی:**
   /start - شروع ربات
   /help - راهنما

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

🎯 **نکات دانلود:**
━━━━━━━━━━━━━━━━━━
1️⃣ لینک رو مستقیم بفرستید
2️⃣ ربات خودش تشخیص میده
3️⃣ منتظر بمونید تا آپلود شه

💡 **مثال‌ها:**
━━━━━━━━━━━━━━━━━━
🔹 ویدیو یوتیوب:
   https://youtube.com/...
   
🔹 ویدیو تیک‌تاک:
   https://tiktok.com/...
   
🔹 صوتی:
   https://youtube.com/... mp3

⚠️ **نکته تیک‌تاک:**
━━━━━━━━━━━━━━━━━━
تیک‌تاک گاهی محدودیت داره. اگه خطا دیدید، دوباره امتحان کنید.

📢 **کانال ما:** @IdTOP_TOPY
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
        InlineKeyboardButton("🌐 سایت‌ها", callback_data="sites")
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
        InlineKeyboardButton("👥 کاربران", callback_data="show_users"),
        InlineKeyboardButton("👥 گروه‌ها", callback_data="show_groups"),
        InlineKeyboardButton("📥 دانلودها", callback_data="show_downloads"),
        InlineKeyboardButton("📊 آمار", callback_data="show_stats"),
        InlineKeyboardButton("🔄 ریست آمار", callback_data="reset_stats"),
        InlineKeyboardButton("🔒 بلاک کاربر", callback_data="block_user"),
        InlineKeyboardButton("🔓 آنبلاک کاربر", callback_data="unblock_user"),
        InlineKeyboardButton("👥 حالت گروه", callback_data="toggle_group"),
        InlineKeyboardButton("👤 حالت خصوصی", callback_data="toggle_private")
    )
    
    text = f"""
╔══════════════════════════╗
║     👑 **پنل مدیریت**     ║
╚══════════════════════════╝

📊 **آمار کلی:**
━━━━━━━━━━━━━━━━━━
👥 کاربران: {stats['total_users']} نفر
👥 گروه‌ها: {stats['total_groups']} گروه
📥 دانلودها: {stats['total_downloads']}

📈 **امروز:**
━━━━━━━━━━━━━━━━━━
👤 کاربران جدید: {stats['today_users']}
👥 گروه‌های فعال: {stats['active_groups']}
📊 دانلودها: {stats['today_downloads']}

🟢 **وضعیت:**
━━━━━━━━━━━━━━━━━━
ربات: {'روشن ✅' if stats['bot_status'] == 'ON' else 'خاموش ❌'}
گروه: {'فعال ✅' if stats['group_mode'] == 'ON' else 'غیرفعال ❌'}
خصوصی: {'فعال ✅' if stats['private_mode'] == 'ON' else 'غیرفعال ❌'}

🔒 کاربران بلاک: {stats['blocked']}
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
            InlineKeyboardButton("🌐 سایت‌ها", callback_data="sites")
        )
        bot.edit_message_text(WELCOME_MESSAGE, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "help":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_start"))
        bot.edit_message_text(HELP_MESSAGE, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "sites":
        sites_text = """
╔══════════════════════════╗
║    🌐 **سایت‌های پشتیبانی**   ║
╚══════════════════════════╝

✅ **پشتیبانی شده:**
━━━━━━━━━━━━━━━━━━
• YouTube ✅
• TikTok ✅ (با تنظیمات ویژه)
• Instagram ✅
• Twitter/X ✅
• Facebook ✅
• Vimeo ✅
• Dailymotion ✅
• SoundCloud ✅
• Pinterest ✅
• Flickr ✅
• و بیش از ۱۰۰۰ سایت دیگر

⚠️ **نکته تیک‌تاک:**
━━━━━━━━━━━━━━━━━━
تیک‌تاک محدودیت‌های زیادی داره.
اگه خطا دیدید، چند بار امتحان کنید.
        """
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_start"))
        bot.edit_message_text(sites_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    # بخش ادمین
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید")
        return
    
    if call.data == "toggle_on":
        db.set_setting('bot_status', 'ON')
        bot.answer_callback_query(call.id, "✅ ربات روشن شد")
        bot.edit_message_text("✅ ربات با موفقیت روشن شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "toggle_off":
        db.set_setting('bot_status', 'OFF')
        bot.answer_callback_query(call.id, "✅ ربات خاموش شد")
        bot.edit_message_text("✅ ربات با موفقیت خاموش شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "toggle_group":
        new = db.toggle_group_mode()
        bot.answer_callback_query(call.id, f"✅ حالت گروه {new} شد")
        bot.edit_message_text(f"✅ حالت گروه {new} شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "toggle_private":
        new = db.toggle_private_mode()
        bot.answer_callback_query(call.id, f"✅ حالت خصوصی {new} شد")
        bot.edit_message_text(f"✅ حالت خصوصی {new} شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "show_stats":
        stats = db.get_stats()
        text = f"""
📊 **آمار کامل**

👥 **کاربران:**
• کل: {stats['total_users']}
• جدید امروز: {stats['today_users']}
• فعال امروز: {stats['active_today']}
• بلاک شده: {stats['blocked']}

👥 **گروه‌ها:**
• کل: {stats['total_groups']}
• جدید امروز: {stats['today_groups']}
• فعال امروز: {stats['active_groups']}

📥 **دانلودها:**
• کل: {stats['total_downloads']}
• امروز: {stats['today_downloads']}

🟢 **وضعیت:**
• ربات: {stats['bot_status']}
• گروه: {stats['group_mode']}
• خصوصی: {stats['private_mode']}
        """
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "show_users":
        users = db.get_users(20)
        text = "👥 **۲۰ کاربر آخر:**\n\n"
        for u in users[:10]:
            status = "🔒" if u[6] else "✅"
            admin = "👑" if u[7] else ""
            name = u[2] or u[1] or 'ناشناس'
            text += f"{admin}{status} `{u[0]}` | {name} | دانلود: {u[5]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "show_groups":
        groups = db.get_groups(20)
        text = "👥 **۲۰ گروه آخر:**\n\n"
        for g in groups[:10]:
            status = "✅" if g[4] else "❌"
            text += f"{status} `{g[0]}` | {g[1][:30]} | {g[3][:16]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "show_downloads":
        downloads = db.get_recent_downloads(10)
        text = "📥 **۱۰ دانلود آخر:**\n\n"
        for d in downloads:
            name = d[9] or d[8] or 'ناشناس'
            group = f" در {d[10][:20]}" if d[10] else ""
            text += f"• {name}{group} | {d[3]} | {d[5]} بایت | {d[11]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "reset_stats":
        db.reset_stats()
        bot.answer_callback_query(call.id, "✅ آمار ریست شد")
        bot.edit_message_text("✅ آمار با موفقیت ریست شد", call.message.chat.id, call.message.message_id)
    
    elif call.data == "block_user":
        bot.edit_message_text("🔒 آیدی کاربر مورد نظر برای بلاک رو بفرست:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(call.message, block_user_handler)
    
    elif call.data == "unblock_user":
        bot.edit_message_text("🔓 آیدی کاربر مورد نظر برای آنبلاک رو بفرست:", call.message.chat.id, call.message.message_id)
        bot.register_next_step_handler(call.message, unblock_user_handler)

def block_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.block_user(user_id)
        bot.reply_to(message, f"✅ کاربر {user_id} بلاک شد")
    except:
        bot.reply_to(message, "❌ آیدی نامعتبر")

def unblock_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.unblock_user(user_id)
        bot.reply_to(message, f"✅ کاربر {user_id} آنبلاک شد")
    except:
        bot.reply_to(message, "❌ آیدی نامعتبر")

# ================= پردازش پیام‌ها =================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text
    
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
        return
    
    # بررسی حالت گروه
    if message.chat.type in ['group', 'supergroup'] and db.get_setting('group_mode') == 'OFF':
        return
    
    # بررسی حالت خصوصی
    if message.chat.type == 'private' and db.get_setting('private_mode') == 'OFF':
        bot.reply_to(message, "❌ حالت خصوصی غیرفعال است")
        return
    
    # استخراج لینک‌ها
    urls = extract_urls(text)
    
    if urls:
        platform = detect_platform(urls[0])
        bot.reply_to(message, f"✅ **لینک {platform} دریافت شد، دانلود شروع شد...**", parse_mode="Markdown")
        is_group = message.chat.type in ['group', 'supergroup']
        threading.Thread(target=download_video, args=(urls[0], chat_id, user_id, message, is_group)).start()

# ================= پنل وب =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <title>پنل مدیریت ربات</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Vazir', Tahoma, Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            margin-bottom: 20px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            border-right: 5px solid #667eea;
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
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            border-bottom: 3px solid #667eea;
        }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
        }
        .status-badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: bold;
            margin: 10px 0;
        }
        .status-on { background: #4caf50; color: white; }
        .status-off { background: #f44336; color: white; }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            margin: 5px;
            font-weight: bold;
        }
        .btn-success { background: #4caf50; color: white; }
        .btn-danger { background: #f44336; color: white; }
        .btn-primary { background: #667eea; color: white; }
        .btn-warning { background: #ff9800; color: white; }
        table {
            width: 100%;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: right;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #f0f0f0;
        }
        tr:hover { background: #f8f9fa; }
        .footer {
            text-align: center;
            color: white;
            margin-top: 20px;
            padding: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 پنل مدیریت ربات دانلود</h1>
            <div class="status-badge {{ 'status-on' if stats.bot_status == 'ON' else 'status-off' }}">
                وضعیت: {{ 'روشن' if stats.bot_status == 'ON' else 'خاموش' }}
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div>👥 کل کاربران</div>
                <div class="stat-value">{{ stats.total_users }}</div>
            </div>
            <div class="stat-card">
                <div>👥 کل گروه‌ها</div>
                <div class="stat-value">{{ stats.total_groups }}</div>
            </div>
            <div class="stat-card">
                <div>📥 کل دانلودها</div>
                <div class="stat-value">{{ stats.total_downloads }}</div>
            </div>
            <div class="stat-card">
                <div>📊 دانلود امروز</div>
                <div class="stat-value">{{ stats.today_downloads }}</div>
            </div>
            <div class="stat-card">
                <div>🟢 فعال امروز</div>
                <div class="stat-value">{{ stats.active_today }}</div>
            </div>
            <div class="stat-card">
                <div>🔒 بلاک شده</div>
                <div class="stat-value">{{ stats.blocked }}</div>
            </div>
        </div>
        
        <div style="text-align: center; margin: 20px 0;">
            <a href="/toggle/on" class="btn btn-success">🟢 روشن</a>
            <a href="/toggle/off" class="btn btn-danger">🔴 خاموش</a>
            <a href="/reset" class="btn btn-warning" onclick="return confirm('آیا مطمئنی؟')">🔄 ریست آمار</a>
        </div>
        
        <h3 style="color: white; margin: 20px 0;">👥 آخرین کاربران</h3>
        <table>
            <tr>
                <th>آیدی</th>
                <th>نام</th>
                <th>دانلودها</th>
                <th>وضعیت</th>
                <th>آخرین بازدید</th>
            </tr>
            {% for u in users %}
            <tr>
                <td>{{ u[0] }}</td>
                <td>{{ u[2] or u[1] or 'ناشناس' }}</td>
                <td>{{ u[5] }}</td>
                <td>{{ '🔒 بلاک' if u[6] else '✅ فعال' }}</td>
                <td>{{ u[4][:16] if u[4] else 'نامشخص' }}</td>
            </tr>
            {% endfor %}
        </table>
        
        <h3 style="color: white; margin: 20px 0;">👥 آخرین گروه‌ها</h3>
        <table>
            <tr>
                <th>آیدی</th>
                <th>نام گروه</th>
                <th>وضعیت</th>
                <th>آخرین فعالیت</th>
            </tr>
            {% for g in groups %}
            <tr>
                <td>{{ g[0] }}</td>
                <td>{{ g[1][:30] }}</td>
                <td>{{ '✅ فعال' if g[4] else '❌ غیرفعال' }}</td>
                <td>{{ g[3][:16] }}</td>
            </tr>
            {% endfor %}
        </table>
        
        <h3 style="color: white; margin: 20px 0;">📥 آخرین دانلودها</h3>
        <table>
            <tr>
                <th>کاربر</th>
                <th>پلتفرم</th>
                <th>فرمت</th>
                <th>حجم</th>
                <th>منبع</th>
                <th>زمان</th>
            </tr>
            {% for d in downloads %}
            <tr>
                <td>{{ d[8] or d[9] or d[1] }}</td>
                <td>{{ d[11] }}</td>
                <td>{{ d[3] }}</td>
                <td>{{ d[5] }} بایت</td>
                <td>{{ '👥 گروه' if d[10] == 'group' else '👤 خصوصی' }}</td>
                <td>{{ d[6][:16] }}</td>
            </tr>
            {% endfor %}
        </table>
        
        <div class="footer">
            <p>🤖 ربات دانلود حرفه‌ای | ساخته شده با ❤️</p>
            <p>📢 کانال: @IdTOP_TOPY</p>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    stats = db.get_stats()
    users = db.get_users(10)
    groups = db.get_groups(10)
    downloads = db.get_recent_downloads(10)
    return render_template_string(HTML_TEMPLATE, stats=stats, users=users, groups=groups, downloads=downloads)

@app.route('/toggle/<status>')
def toggle(status):
    if status in ['on', 'off']:
        db.set_setting('bot_status', 'ON' if status == 'on' else 'OFF')
    return redirect('/')

@app.route('/reset')
def reset():
    db.reset_stats()
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
    
    if not HAS_CURL_CFFI:
        print("""
⚠️ **هشدار تیک‌تاک:**
   curl_cffi نصب نیست! برای دانلود تیک‌تاک باید نصب بشه:
   pip install curl_cffi
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
