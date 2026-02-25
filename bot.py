# -*- coding: utf-8 -*-
import os
import threading
from queue import Queue
from datetime import datetime
import sqlite3
from flask import Flask, request, redirect, render_template_string, jsonify
import yt_dlp
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import logging
import sys
import signal

# ================= تنظیمات لاگ =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ================= توکن و ادمین - مقادیر واقعی =================
# دیگه از رمزگشایی استفاده نمی‌کنیم
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292

logger.info(f"✅ توکن: {TOKEN[:10]}...")
logger.info(f"✅ ادمین: {ADMIN_ID}")

# ================= تنظیمات =================
class Config:
    MAX_FILE_SIZE = 300 * 1024 * 1024  # 300 مگابایت
    DOWNLOAD_PATH = "downloads"
    WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
    WEBHOOK_HOST = "0.0.0.0"
    WEBHOOK_PORT = int(os.environ.get('PORT', 8080))  # از پورت 8080 استفاده کن
    USE_WEBHOOK = True
    DEBUG = False

config = Config()

# ================= ایجاد پوشه‌ها =================
os.makedirs(config.DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= راه‌اندازی ربات =================
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ================= دیتابیس پیشرفته =================
class Database:
    def __init__(self, db_path='database/bot.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # جدول کاربران
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TIMESTAMP,
                last_active TIMESTAMP,
                blocked INTEGER DEFAULT 0,
                downloads_count INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                language TEXT DEFAULT 'fa'
            )
            """)
            
            # جدول آمار
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE,
                total_downloads INTEGER DEFAULT 0,
                total_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0
            )
            """)
            
            # جدول تنظیمات
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)
            
            # جدول دانلودها
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                url TEXT,
                format TEXT,
                title TEXT,
                filesize INTEGER,
                status TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """)
            
            # جدول پیام‌های همگانی
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                completed_at TIMESTAMP
            )
            """)
            
            # تنظیمات پیش‌فرض
            default_settings = [
                ('bot_status', 'ON'),
                ('maintenance_mode', 'OFF'),
                ('total_downloads', '0'),
                ('total_users', '0'),
                ('created_at', str(datetime.now()))
            ]
            
            for key, value in default_settings:
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
            
            # تنظیم ادمین
            cursor.execute("INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, 1)", (ADMIN_ID,))
            
            conn.commit()
            conn.close()
            logger.info("✅ دیتابیس پیشرفته راه‌اندازی شد")
    
    def execute(self, query, params=(), fetch_one=False, fetch_all=False):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                
                if query.strip().upper().startswith('SELECT'):
                    if fetch_one:
                        result = cursor.fetchone()
                    elif fetch_all:
                        result = cursor.fetchall()
                    else:
                        result = cursor.fetchall()
                else:
                    conn.commit()
                    result = cursor.lastrowid
                
                return result
            except Exception as e:
                logger.error(f"خطای دیتابیس: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def add_user(self, user_id, username=None, first_name=None, last_name=None):
        now = datetime.now()
        try:
            user = self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch_one=True)
            
            if user:
                self.execute("UPDATE users SET last_active = ?, username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                           (now, username, first_name, last_name, user_id))
            else:
                self.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, joined_date, last_active, blocked, downloads_count, is_admin, language)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, 'fa')
                """, (user_id, username, first_name, last_name, now, now, 1 if user_id == ADMIN_ID else 0))
                
                date_str = now.strftime('%Y-%m-%d')
                self.execute("INSERT INTO stats (date, total_users) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET total_users = total_users + 1", (date_str,))
            
            return True
        except Exception as e:
            logger.error(f"خطا در add_user: {e}")
            return False
    
    def is_blocked(self, user_id):
        result = self.execute("SELECT blocked FROM users WHERE user_id = ?", (user_id,), fetch_one=True)
        return result and result[0] == 1 if result else False
    
    def is_bot_on(self):
        result = self.execute("SELECT value FROM settings WHERE key = 'bot_status'", fetch_one=True)
        return result and result[0] == 'ON' if result else True
    
    def update_stats(self, user_id, url, fmt, title=None, filesize=None, status='success'):
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        
        try:
            self.execute("INSERT INTO downloads (user_id, url, format, title, filesize, status, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (user_id, url, fmt, title, filesize, status, now))
            
            self.execute("UPDATE users SET downloads_count = downloads_count + 1, last_active = ? WHERE user_id = ?", (now, user_id))
            
            self.execute("INSERT INTO stats (date, total_downloads) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET total_downloads = total_downloads + 1", (date_str,))
            
            self.execute("UPDATE settings SET value = value + 1 WHERE key = 'total_downloads'")
            
        except Exception as e:
            logger.error(f"خطا در update_stats: {e}")
    
    def get_stats(self):
        today = datetime.now().strftime('%Y-%m-%d')
        
        total_users = self.execute("SELECT COUNT(*) as count FROM users", fetch_one=True)
        today_active = self.execute("SELECT COUNT(*) as count FROM users WHERE date(last_active) = date('now')", fetch_one=True)
        blocked_users = self.execute("SELECT COUNT(*) as count FROM users WHERE blocked = 1", fetch_one=True)
        total_downloads = self.execute("SELECT value FROM settings WHERE key = 'total_downloads'", fetch_one=True)
        today_downloads = self.execute("SELECT total_downloads FROM stats WHERE date = ?", (today,), fetch_one=True)
        
        return {
            'total_users': total_users[0] if total_users else 0,
            'today_active': today_active[0] if today_active else 0,
            'blocked_users': blocked_users[0] if blocked_users else 0,
            'total_downloads': int(total_downloads[0]) if total_downloads else 0,
            'today_downloads': today_downloads[0] if today_downloads else 0
        }
    
    def set_bot_status(self, status):
        self.execute("UPDATE settings SET value = ? WHERE key = 'bot_status'", (status,))
    
    def block_user(self, user_id):
        self.execute("UPDATE users SET blocked = 1 WHERE user_id = ?", (user_id,))
    
    def unblock_user(self, user_id):
        self.execute("UPDATE users SET blocked = 0 WHERE user_id = ?", (user_id,))
    
    def get_users(self, limit=50, blocked_only=False):
        query = "SELECT * FROM users"
        params = []
        if blocked_only:
            query += " WHERE blocked = 1"
        query += " ORDER BY last_active DESC LIMIT ?"
        params.append(limit)
        return self.execute(query, params, fetch_all=True)
    
    def get_recent_downloads(self, limit=20):
        return self.execute("""
            SELECT d.*, u.username, u.first_name 
            FROM downloads d
            LEFT JOIN users u ON d.user_id = u.user_id
            ORDER BY d.timestamp DESC
            LIMIT ?
        """, (limit,), fetch_all=True)

# ================= ایجاد دیتابیس =================
db = Database()

# ================= صف دانلود =================
download_queue = Queue()

# ================= Worker برای دانلود =================
def download_worker():
    while True:
        try:
            task = download_queue.get()
            if task:
                chat_id, user_id, url, fmt, message_id = task
                process_download_task(chat_id, user_id, url, fmt, message_id)
            download_queue.task_done()
        except Exception as e:
            logger.error(f"خطا در worker: {e}")
        time.sleep(1)

for i in range(3):
    threading.Thread(target=download_worker, daemon=True).start()

def process_download_task(chat_id, user_id, url, fmt, status_message_id):
    try:
        if db.is_blocked(user_id):
            bot.edit_message_text("⛔ شما بلاک هستید.", chat_id, status_message_id)
            return
        
        if not db.is_bot_on():
            bot.edit_message_text("⛔ ربات خاموش است.", chat_id, status_message_id)
            return
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'outtmpl': f'{config.DOWNLOAD_PATH}/%(title)s.%(ext)s',
            'format': 'best[filesize<300M]' if fmt == 'mp4' else 'bestaudio/best',
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
            'ignoreerrors': True,
            'no_color': True,
        }
        
        if fmt == 'mp3':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['format'] = 'bestaudio/best'
        elif fmt == 'best':
            ydl_opts['format'] = 'best[filesize<300M]'
        
        bot.edit_message_text("⏳ در حال دریافت اطلاعات...", chat_id, status_message_id)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown')
            extractor = info.get('extractor', 'unknown')
            
            logger.info(f"📥 دانلود از {extractor}: {title}")
            
            filename = None
            if fmt == 'mp3':
                possible_filename = f"{config.DOWNLOAD_PATH}/{title}.mp3"
                if os.path.exists(possible_filename):
                    filename = possible_filename
                else:
                    for f in os.listdir(config.DOWNLOAD_PATH):
                        if f.endswith('.mp3') and title in f:
                            filename = os.path.join(config.DOWNLOAD_PATH, f)
                            break
            else:
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    for f in os.listdir(config.DOWNLOAD_PATH):
                        if title in f:
                            filename = os.path.join(config.DOWNLOAD_PATH, f)
                            break
            
            if filename and os.path.exists(filename):
                filesize = os.path.getsize(filename)
                
                if filesize <= config.MAX_FILE_SIZE:
                    bot.edit_message_text("📤 در حال آپلود...", chat_id, status_message_id)
                    
                    with open(filename, 'rb') as f:
                        if fmt == 'mp3' or filename.endswith(('.mp3', '.m4a', '.ogg')):
                            bot.send_audio(chat_id, f, caption=f"🎵 {title}", title=title, performer="Unknown", duration=info.get('duration', 0))
                        elif filename.endswith(('.mp4', '.mkv', '.webm')):
                            bot.send_video(chat_id, f, caption=f"🎬 {title}", duration=info.get('duration', 0))
                        elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            bot.send_photo(chat_id, f, caption=f"🖼️ {title}")
                        else:
                            bot.send_document(chat_id, f, caption=f"📄 {title}")
                    
                    db.update_stats(user_id, url, fmt, title, filesize)
                    bot.delete_message(chat_id, status_message_id)
                else:
                    bot.edit_message_text(f"❌ حجم فایل بیشتر از {config.MAX_FILE_SIZE // (1024*1024)} مگابایت است.", chat_id, status_message_id)
                
                try:
                    os.remove(filename)
                except:
                    pass
            else:
                bot.edit_message_text("❌ فایل پیدا نشد.", chat_id, status_message_id)
    
    except yt_dlp.utils.DownloadError as e:
        bot.edit_message_text(f"❌ خطای دانلود: {str(e)[:100]}", chat_id, status_message_id)
        logger.error(f"خطای دانلود: {e}")
    except Exception as e:
        bot.edit_message_text(f"❌ خطا: {str(e)[:100]}", chat_id, status_message_id)
        logger.error(f"خطای دانلود: {e}")

# ================= دستورات ربات =================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    db.add_user(user_id, username, first_name, last_name)
    
    welcome_text = """
🎬 **ربات دانلود از همه سایت‌ها**

🔹 لینک هر ویدیو، عکس، فایل یا موزیک رو بفرست
🔹 پشتیبانی از یوتیوب، اینستاگرام، تیک‌تاک، توییتر و هزاران سایت دیگر
🔹 حداکثر حجم: ۳۰۰ مگابایت

🚀 **نحوه استفاده:**
1️⃣ لینک رو بفرست
2️⃣ فرمت مورد نظر رو انتخاب کن
3️⃣ منتظر دانلود بمون
    """
    
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 روشن", callback_data="admin_on"),
        InlineKeyboardButton("🔴 خاموش", callback_data="admin_off"),
        InlineKeyboardButton("📊 آمار", callback_data="admin_stats"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔒 بلاک/آنبلاک", callback_data="admin_block"),
        InlineKeyboardButton("👥 کاربران", callback_data="admin_users"),
        InlineKeyboardButton("📥 دانلودها", callback_data="admin_downloads"),
        InlineKeyboardButton("🔄 ریست آمار", callback_data="admin_reset")
    )
    
    status_text = f"""
👑 **پنل مدیریت**

📊 **آمار سریع:**
👥 کل کاربران: {stats['total_users']}
📥 کل دانلودها: {stats['total_downloads']}
📊 دانلود امروز: {stats['today_downloads']}
🔒 بلاک شده: {stats['blocked_users']}
🟢 وضعیت: {'روشن' if db.is_bot_on() else 'خاموش'}

لطفاً یکی از گزینه‌ها رو انتخاب کن:
    """
    
    bot.send_message(message.chat.id, status_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید")
        return
    
    action = call.data.replace('admin_', '')
    
    if action == "on":
        db.set_bot_status('ON')
        bot.answer_callback_query(call.id, "✅ ربات روشن شد")
        bot.edit_message_text("✅ ربات با موفقیت روشن شد", call.message.chat.id, call.message.message_id)
    
    elif action == "off":
        db.set_bot_status('OFF')
        bot.answer_callback_query(call.id, "✅ ربات خاموش شد")
        bot.edit_message_text("✅ ربات با موفقیت خاموش شد", call.message.chat.id, call.message.message_id)
    
    elif action == "stats":
        stats = db.get_stats()
        users = db.get_users(limit=10)
        
        text = f"""
📊 **آمار کامل**

👥 **کاربران:**
• کل: {stats['total_users']}
• فعال امروز: {stats['today_active']}
• بلاک شده: {stats['blocked_users']}

📥 **دانلودها:**
• کل: {stats['total_downloads']}
• امروز: {stats['today_downloads']}

🟢 **وضعیت:** {'روشن' if db.is_bot_on() else 'خاموش'}

👤 **۱۰ کاربر آخر:**
"""
        
        for user in users[:5]:
            name = user[2] or user[1] or 'ناشناس'
            text += f"• `{user[0]}` | {name} | دانلود: {user[7]}\n"
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif action == "broadcast":
        bot.edit_message_text("📢 **پیام همگانی جدید**\n\nلطفاً متن پیام رو بفرست:", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, broadcast_handler)
    
    elif action == "block":
        bot.edit_message_text("🔒 **مدیریت بلاک**\n\nآیدی عددی کاربر مورد نظر رو بفرست:", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, block_handler)
    
    elif action == "users":
        users = db.get_users(limit=20)
        text = "👥 **لیست کاربران:**\n\n"
        for user in users:
            status = "🔒" if user[6] else "✅"
            name = user[2] or user[1] or 'ناشناس'
            text += f"{status} `{user[0]}` | {name} | دانلود: {user[7]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif action == "downloads":
        downloads = db.get_recent_downloads(limit=15)
        text = "📥 **آخرین دانلودها:**\n\n"
        for dl in downloads:
            name = dl[9] or dl[8] or 'ناشناس'
            text += f"• {name} | {dl[3]} | {dl[7][:16]}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif action == "reset":
        db.execute("DELETE FROM downloads")
        db.execute("UPDATE settings SET value = '0' WHERE key = 'total_downloads'")
        bot.answer_callback_query(call.id, "✅ آمار ریست شد")
        bot.edit_message_text("✅ تمام آمار با موفقیت ریست شد", call.message.chat.id, call.message.message_id)

def broadcast_handler(message):
    msg_text = message.text
    users = db.get_users(limit=1000)
    
    status_msg = bot.reply_to(message, "📤 در حال ارسال پیام همگانی...")
    
    sent = 0
    failed = 0
    
    for user in users:
        user_id = user[0]
        if not user[6]:
            try:
                bot.send_message(user_id, f"📢 **پیام همگانی**\n\n{msg_text}", parse_mode="Markdown")
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"خطا در ارسال به {user_id}: {e}")
            time.sleep(0.05)
    
    bot.edit_message_text(f"✅ **نتیجه ارسال همگانی**\n\n📤 ارسال شده: {sent}\n❌ ناموفق: {failed}", status_msg.chat.id, status_msg.message_id, parse_mode="Markdown")

def block_handler(message):
    try:
        user_id = int(message.text.strip())
        
        user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch_one=True)
        
        if user:
            if user[6]:
                db.unblock_user(user_id)
                bot.reply_to(message, f"✅ کاربر {user_id} آنبلاک شد.")
            else:
                db.block_user(user_id)
                bot.reply_to(message, f"✅ کاربر {user_id} بلاک شد.")
        else:
            db.execute("INSERT INTO users (user_id, blocked, joined_date) VALUES (?, 1, ?)", (user_id, datetime.now()))
            bot.reply_to(message, f"✅ کاربر جدید {user_id} بلاک شد.")
    
    except ValueError:
        bot.reply_to(message, "❌ لطفاً یک آیدی عددی معتبر بفرست.")
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {e}")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    url = message.text.strip()
    user_id = message.from_user.id
    
    db.add_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    if not url.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ لطفاً یک لینک معتبر بفرست.")
        return
    
    if db.is_blocked(user_id):
        bot.reply_to(message, "⛔ شما بلاک هستید.")
        return
    
    if not db.is_bot_on():
        bot.reply_to(message, "⛔ ربات خاموش است.")
        return
    
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor', 'unknown')
            title = info.get('title', 'Unknown')
            
            markup = InlineKeyboardMarkup(row_width=2)
            
            if info.get('formats'):
                markup.add(
                    InlineKeyboardButton("🎵 MP3 (صوت)", callback_data=f"dl_mp3_{url}"),
                    InlineKeyboardButton("🎬 MP4 (ویدیو)", callback_data=f"dl_mp4_{url}"),
                    InlineKeyboardButton("📥 بهترین کیفیت", callback_data=f"dl_best_{url}")
                )
            else:
                markup.add(InlineKeyboardButton("📥 دانلود فایل", callback_data=f"dl_best_{url}"))
            
            bot.reply_to(message, f"🔍 **منبع:** {extractor}\n📌 **عنوان:** {title[:50]}...\n\n📥 **فرمت مورد نظر رو انتخاب کن:**", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🎵 MP3 (صوت)", callback_data=f"dl_mp3_{url}"),
            InlineKeyboardButton("🎬 MP4 (ویدیو)", callback_data=f"dl_mp4_{url}"),
            InlineKeyboardButton("📥 بهترین کیفیت", callback_data=f"dl_best_{url}")
        )
        bot.reply_to(message, "📥 **فرمت مورد نظر رو انتخاب کن:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def download_callback(call):
    try:
        parts = call.data.split('_', 2)
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "❌ لینک نامعتبر")
            return
            
        fmt = parts[1]
        url = parts[2]
        
        status_msg = bot.send_message(call.message.chat.id, "⏳ اضافه شدن به صف دانلود...")
        
        task = (call.message.chat.id, call.from_user.id, url, fmt, status_msg.message_id)
        download_queue.put(task)
        
        queue_size = download_queue.qsize()
        bot.edit_message_text(f"✅ به صف دانلود اضافه شد\n📊 موقعیت در صف: {queue_size}", call.message.chat.id, status_msg.message_id)
        bot.answer_callback_query(call.id, "✅ درخواست ثبت شد")
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ خطا: {str(e)[:30]}")

# ================= Webhook =================
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return 'OK', 200
        except Exception as e:
            logger.error(f"خطا در پردازش webhook: {e}")
            return 'Error', 500
    return 'Invalid request', 403

# ================= مسیرهای تست =================
@app.route('/test', methods=['GET'])
def test():
    return f"Bot is running! Webhook URL: {config.WEBHOOK_URL}", 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'webhook_url': config.WEBHOOK_URL
    }), 200

# ================= پنل وب پیشرفته =================
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
            font-family: 'Tahoma', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: rgba(255, 255, 255, 0.95);
            padding: 30px;
            border-radius: 20px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
        }
        .header h1 { color: #333; font-size: 28px; margin-bottom: 10px; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: rgba(255, 255, 255, 0.95);
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-icon { font-size: 40px; margin-bottom: 15px; }
        .stat-title { color: #666; font-size: 14px; margin-bottom: 10px; }
        .stat-value { color: #333; font-size: 32px; font-weight: bold; }
        .status-badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 50px;
            font-weight: bold;
            font-size: 14px;
            margin: 10px 0;
        }
        .status-on { background: #4caf50; color: white; }
        .status-off { background: #f44336; color: white; }
        .section {
            background: rgba(255, 255, 255, 0.95);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }
        .section h2 {
            color: #333;
            font-size: 20px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
        }
        .btn {
            display: inline-block;
            padding: 12px 25px;
            border: none;
            border-radius: 50px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            margin: 5px;
            text-decoration: none;
        }
        .btn-success { background: #4caf50; color: white; }
        .btn-danger { background: #f44336; color: white; }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        .btn-warning { background: #ff9800; color: white; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; color: #333; margin-bottom: 8px; font-weight: bold; }
        .form-control {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 14px;
        }
        textarea.form-control { min-height: 120px; resize: vertical; }
        .table {
            width: 100%;
            border-collapse: collapse;
        }
        .table th, .table td {
            padding: 12px;
            text-align: right;
            border-bottom: 1px solid #f0f0f0;
        }
        .table th { background: #f8f9fa; color: #333; font-weight: bold; }
        .table tr:hover { background: #f8f9fa; }
        .footer {
            text-align: center;
            color: rgba(255,255,255,0.8);
            margin-top: 30px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 پنل مدیریت ربات</h1>
            <p>خوش آمدید، ادمین</p>
            <div class="status-badge {% if bot_status == 'ON' %}status-on{% else %}status-off{% endif %}">
                وضعیت ربات: {% if bot_status == 'ON' %}🟢 روشن{% else %}🔴 خاموش{% endif %}
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon">👥</div>
                <div class="stat-title">کل کاربران</div>
                <div class="stat-value">{{ stats.total_users }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">📥</div>
                <div class="stat-title">کل دانلودها</div>
                <div class="stat-value">{{ stats.total_downloads }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">📊</div>
                <div class="stat-title">دانلود امروز</div>
                <div class="stat-value">{{ stats.today_downloads }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">🔒</div>
                <div class="stat-title">کاربران بلاک</div>
                <div class="stat-value">{{ stats.blocked_users }}</div>
            </div>
        </div>
        
        <div class="section">
            <h2>🔄 کنترل ربات</h2>
            <form method="POST" action="/toggle" style="display: inline;">
                <button type="submit" name="action" value="on" class="btn btn-success">🟢 روشن کردن</button>
            </form>
            <form method="POST" action="/toggle" style="display: inline;">
                <button type="submit" name="action" value="off" class="btn btn-danger">🔴 خاموش کردن</button>
            </form>
        </div>
        
        <div class="section">
            <h2>📢 پیام همگانی</h2>
            <form method="POST" action="/broadcast">
                <div class="form-group">
                    <label>متن پیام:</label>
                    <textarea name="message" class="form-control" placeholder="متن پیام خود را وارد کنید..." required></textarea>
                </div>
                <button type="submit" class="btn btn-primary">📤 ارسال برای همه کاربران</button>
            </form>
        </div>
        
        <div class="section">
            <h2>🔒 مدیریت کاربران</h2>
            <form method="POST" action="/block_user">
                <div class="form-group">
                    <label>آیدی عددی کاربر:</label>
                    <input type="number" name="user_id" class="form-control" placeholder="مثال: 123456789" required>
                </div>
                <button type="submit" name="action" value="block" class="btn btn-danger">🔒 بلاک کردن</button>
                <button type="submit" name="action" value="unblock" class="btn btn-success">🔓 آنبلاک کردن</button>
            </form>
        </div>
        
        <div class="section">
            <h2>📊 مدیریت آمار</h2>
            <form method="POST" action="/reset_stats" onsubmit="return confirm('آیا از ریست آمار اطمینان دارید؟')">
                <button type="submit" class="btn btn-warning">🔄 ریست آمار دانلودها</button>
            </form>
        </div>
        
        <div class="section">
            <h2>👥 آخرین کاربران</h2>
            <table class="table">
                <thead>
                    <tr>
                        <th>آیدی</th>
                        <th>نام</th>
                        <th>دانلودها</th>
                        <th>وضعیت</th>
                        <th>آخرین فعالیت</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in recent_users %}
                    <tr>
                        <td>{{ user[0] }}</td>
                        <td>{{ user[2] or user[1] or 'ناشناس' }}</td>
                        <td>{{ user[7] }}</td>
                        <td>{% if user[6] %}🔒 بلاک{% else %}✅ فعال{% endif %}</td>
                        <td>{{ user[5][:16] if user[5] else 'نامشخص' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>📥 آخرین دانلودها</h2>
            <table class="table">
                <thead>
                    <tr>
                        <th>کاربر</th>
                        <th>فرمت</th>
                        <th>عنوان</th>
                        <th>زمان</th>
                    </tr>
                </thead>
                <tbody>
                    {% for dl in recent_downloads %}
                    <tr>
                        <td>{{ dl[9] or dl[8] or dl[1] }}</td>
                        <td>{{ dl[3] }}</td>
                        <td>{{ dl[4][:30] }}...</td>
                        <td>{{ dl[7][:16] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>ربات دانلود از همه سایت‌ها | ساخته شده با ❤️</p>
            <p>Webhook: {{ webhook_url }}</p>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    stats = db.get_stats()
    bot_status = db.execute("SELECT value FROM settings WHERE key = 'bot_status'", fetch_one=True)
    recent_users = db.get_users(limit=10)
    recent_downloads = db.get_recent_downloads(limit=10)
    
    return render_template_string(
        HTML_TEMPLATE,
        stats=stats,
        bot_status=bot_status[0] if bot_status else 'ON',
        recent_users=recent_users,
        recent_downloads=recent_downloads,
        webhook_url=config.WEBHOOK_URL
    )

@app.route('/toggle', methods=['POST'])
def toggle():
    action = request.form.get('action')
    if action in ['on', 'off']:
        db.set_bot_status(action.upper())
    return redirect('/')

@app.route('/broadcast', methods=['POST'])
def broadcast():
    message = request.form.get('message')
    if message:
        users = db.get_users(limit=1000)
        sent = 0
        for user in users:
            if not user[6]:
                try:
                    bot.send_message(user[0], f"📢 **پیام همگانی**\n\n{message}", parse_mode="Markdown")
                    sent += 1
                except:
                    pass
                time.sleep(0.05)
        return f"✅ پیام به {sent} کاربر ارسال شد. <a href='/'>بازگشت</a>"
    return redirect('/')

@app.route('/block_user', methods=['POST'])
def block_user():
    try:
        user_id = int(request.form.get('user_id'))
        action = request.form.get('action')
        
        if action == 'block':
            db.block_user(user_id)
            msg = f"✅ کاربر {user_id} بلاک شد."
        else:
            db.unblock_user(user_id)
            msg = f"✅ کاربر {user_id} آنبلاک شد."
        
        return f"{msg} <a href='/'>بازگشت</a>"
    except:
        return "❌ خطا در پردازش. <a href='/'>بازگشت</a>"

@app.route('/reset_stats', methods=['POST'])
def reset_stats():
    db.execute("DELETE FROM downloads")
    db.execute("UPDATE settings SET value = '0' WHERE key = 'total_downloads'")
    return redirect('/')

# ================= تنظیم Webhook =================
def setup_webhook():
    try:
        bot.remove_webhook()
        time.sleep(1)
        success = bot.set_webhook(url=config.WEBHOOK_URL)
        
        if success:
            logger.info(f"✅ Webhook تنظیم شد: {config.WEBHOOK_URL}")
            webhook_info = bot.get_webhook_info()
            logger.info(f"📡 اطلاعات Webhook: {webhook_info}")
            return True
        else:
            logger.error("❌ خطا در تنظیم Webhook")
            return False
    except Exception as e:
        logger.error(f"❌ خطا در تنظیم webhook: {e}")
        return False

# ================= راه‌اندازی =================
def signal_handler(sig, frame):
    logger.info("🛑 در حال خروج از برنامه...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("🚀 در حال راه‌اندازی ربات...")
    logger.info(f"👤 آیدی ادمین: {ADMIN_ID}")
    logger.info(f"🌐 Webhook URL: {config.WEBHOOK_URL}")
    
    if setup_webhook():
        logger.info("✅ Webhook با موفقیت تنظیم شد")
    else:
        logger.warning("⚠️ خطا در تنظیم Webhook - ادامه با polling")
    
    logger.info(f"🚀 اجرا روی پورت {config.WEBHOOK_PORT}")
    app.run(host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT, debug=config.DEBUG, threaded=True)
