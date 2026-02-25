# -*- coding: utf-8 -*-
import os
import threading
from queue import Queue
from datetime import datetime, timedelta
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

# ================= توکن و ادمین - مقادیر مستقیم =================
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
    WEBHOOK_PORT = int(os.environ.get('PORT', 8080))
    USE_WEBHOOK = True
    DEBUG = False
    
    # تنظیمات عضویت اجباری - دو کانال
    FORCE_JOIN_ENABLED = True  # فعال کردن عضویت اجباری
    
    # کانال اول
    FORCE_JOIN_CHANNEL_1 = "@top_topy_downloader"
    FORCE_JOIN_CHANNEL_ID_1 = -1003828073352  # آیدی عددی کانال اول
    
    # کانال دوم
    FORCE_JOIN_CHANNEL_2 = "@IdTOP_TOPY"
    FORCE_JOIN_CHANNEL_ID_2 = -1003872568492  # آیدی عددی کانال دوم
    
    FORCE_JOIN_MESSAGE = "🔒 **برای استفاده از ربات، باید در کانال‌های زیر عضو شوید:**\n\n{channels}\n\nبعد از عضویت، دکمه ✅ بررسی عضویت را بزنید."
    
    # تنظیمات محدودیت دانلود روزانه
    DAILY_LIMIT_ENABLED = False
    DAILY_LIMIT_COUNT = 5

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
                language TEXT DEFAULT 'fa',
                daily_downloads INTEGER DEFAULT 0,
                last_download_date TEXT,
                joined_channel_1 INTEGER DEFAULT 0,
                joined_channel_2 INTEGER DEFAULT 0,
                warning_count INTEGER DEFAULT 0
            )
            """)
            
            # جدول آمار
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE,
                total_downloads INTEGER DEFAULT 0,
                total_users INTEGER DEFAULT 0,
                active_users INTEGER DEFAULT 0,
                total_blocked INTEGER DEFAULT 0
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
            
            # تنظیمات پیش‌فرض
            default_settings = [
                ('bot_status', 'ON'),
                ('maintenance_mode', 'OFF'),
                ('total_downloads', '0'),
                ('total_users', '0'),
                ('total_blocked', '0'),
                ('force_join_enabled', str(config.FORCE_JOIN_ENABLED)),
                ('daily_limit_enabled', str(config.DAILY_LIMIT_ENABLED)),
                ('daily_limit_count', str(config.DAILY_LIMIT_COUNT)),
                ('force_join_channel_1', config.FORCE_JOIN_CHANNEL_1),
                ('force_join_channel_id_1', str(config.FORCE_JOIN_CHANNEL_ID_1)),
                ('force_join_channel_2', config.FORCE_JOIN_CHANNEL_2),
                ('force_join_channel_id_2', str(config.FORCE_JOIN_CHANNEL_ID_2)),
                ('created_at', str(datetime.now()))
            ]
            
            for key, value in default_settings:
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
            
            # تنظیم ادمین
            cursor.execute("INSERT OR IGNORE INTO users (user_id, is_admin) VALUES (?, 1)", (ADMIN_ID,))
            
            conn.commit()
            conn.close()
            logger.info("✅ دیتابیس پیشرفته راه‌اندازی شد")
            logger.info(f"✅ عضویت اجباری در دو کانال فعال شد: {config.FORCE_JOIN_CHANNEL_1} و {config.FORCE_JOIN_CHANNEL_2}")
    
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
        today = now.strftime('%Y-%m-%d')
        
        try:
            user = self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch_one=True)
            
            if user:
                # آپدیت آخرین فعالیت
                self.execute("UPDATE users SET last_active = ?, username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
                           (now, username, first_name, last_name, user_id))
                
                # ریست دانلود روزانه اگه روز جدید باشه
                if user[10] != today:  # last_download_date
                    self.execute("UPDATE users SET daily_downloads = 0, last_download_date = ? WHERE user_id = ?", (today, user_id))
            else:
                # افزودن کاربر جدید
                self.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, joined_date, last_active, blocked, downloads_count, is_admin, language, daily_downloads, last_download_date, joined_channel_1, joined_channel_2, warning_count)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, 'fa', 0, ?, 0, 0, 0)
                """, (user_id, username, first_name, last_name, now, now, 1 if user_id == ADMIN_ID else 0, today))
                
                date_str = now.strftime('%Y-%m-%d')
                self.execute("INSERT INTO stats (date, total_users) VALUES (?, 1) ON CONFLICT(date) DO UPDATE SET total_users = total_users + 1", (date_str,))
            
            return True
        except Exception as e:
            logger.error(f"خطا در add_user: {e}")
            return False
    
    def check_force_join(self, user_id):
        """بررسی عضویت اجباری در هر دو کانال"""
        enabled = self.execute("SELECT value FROM settings WHERE key = 'force_join_enabled'", fetch_one=True)
        if not enabled or enabled[0] != 'True':
            return True
        
        # بررسی کانال اول
        channel_id_1 = self.execute("SELECT value FROM settings WHERE key = 'force_join_channel_id_1'", fetch_one=True)
        channel_1_ok = True
        if channel_id_1:
            try:
                member = bot.get_chat_member(int(channel_id_1[0]), user_id)
                status = member.status
                channel_1_ok = status in ['member', 'administrator', 'creator']
                if channel_1_ok:
                    self.execute("UPDATE users SET joined_channel_1 = 1 WHERE user_id = ?", (user_id,))
            except Exception as e:
                logger.error(f"خطا در بررسی کانال اول: {e}")
                channel_1_ok = False
        
        # بررسی کانال دوم
        channel_id_2 = self.execute("SELECT value FROM settings WHERE key = 'force_join_channel_id_2'", fetch_one=True)
        channel_2_ok = True
        if channel_id_2:
            try:
                member = bot.get_chat_member(int(channel_id_2[0]), user_id)
                status = member.status
                channel_2_ok = status in ['member', 'administrator', 'creator']
                if channel_2_ok:
                    self.execute("UPDATE users SET joined_channel_2 = 1 WHERE user_id = ?", (user_id,))
            except Exception as e:
                logger.error(f"خطا در بررسی کانال دوم: {e}")
                channel_2_ok = False
        
        return channel_1_ok and channel_2_ok
    
    def check_daily_limit(self, user_id):
        enabled = self.execute("SELECT value FROM settings WHERE key = 'daily_limit_enabled'", fetch_one=True)
        if not enabled or enabled[0] != 'True':
            return True
        
        limit = self.execute("SELECT value FROM settings WHERE key = 'daily_limit_count'", fetch_one=True)
        if not limit:
            return True
        
        user = self.execute("SELECT daily_downloads FROM users WHERE user_id = ?", (user_id,), fetch_one=True)
        return user and user[0] < int(limit[0])
    
    def increment_daily_download(self, user_id):
        today = datetime.now().strftime('%Y-%m-%d')
        self.execute("""
            UPDATE users 
            SET daily_downloads = daily_downloads + 1, last_download_date = ? 
            WHERE user_id = ?
        """, (today, user_id))
    
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
            
            self.increment_daily_download(user_id)
            
            self.execute("""
                INSERT INTO stats (date, total_downloads) VALUES (?, 1) 
                ON CONFLICT(date) DO UPDATE SET total_downloads = total_downloads + 1
            """, (date_str,))
            
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
        
        total_admins = self.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 1", fetch_one=True)
        joined_channel_1 = self.execute("SELECT COUNT(*) as count FROM users WHERE joined_channel_1 = 1", fetch_one=True)
        joined_channel_2 = self.execute("SELECT COUNT(*) as count FROM users WHERE joined_channel_2 = 1", fetch_one=True)
        
        return {
            'total_users': total_users[0] if total_users else 0,
            'today_active': today_active[0] if today_active else 0,
            'blocked_users': blocked_users[0] if blocked_users else 0,
            'total_downloads': int(total_downloads[0]) if total_downloads else 0,
            'today_downloads': today_downloads[0] if today_downloads else 0,
            'total_admins': total_admins[0] if total_admins else 0,
            'joined_channel_1': joined_channel_1[0] if joined_channel_1 else 0,
            'joined_channel_2': joined_channel_2[0] if joined_channel_2 else 0
        }
    
    def set_bot_status(self, status):
        self.execute("UPDATE settings SET value = ? WHERE key = 'bot_status'", (status,))

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
        
        if not db.check_daily_limit(user_id):
            limit = db.execute("SELECT value FROM settings WHERE key = 'daily_limit_count'", fetch_one=True)
            bot.edit_message_text(f"❌ شما به محدودیت دانلود روزانه ({limit[0]} فایل) رسیده‌اید.", chat_id, status_message_id)
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
                            bot.send_audio(chat_id, f, caption=f"🎵 {title}", title=title, performer="YouTube", duration=info.get('duration', 0))
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
    
    # بررسی عضویت اجباری در دو کانال
    if not db.check_force_join(user_id):
        channel_1 = db.execute("SELECT value FROM settings WHERE key = 'force_join_channel_1'", fetch_one=True)
        channel_2 = db.execute("SELECT value FROM settings WHERE key = 'force_join_channel_2'", fetch_one=True)
        
        channel_link_1 = f"https://t.me/{channel_1[0].replace('@', '')}" if channel_1 else ""
        channel_link_2 = f"https://t.me/{channel_2[0].replace('@', '')}" if channel_2 else ""
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📢 کانال اول", url=channel_link_1),
            InlineKeyboardButton("📢 کانال دوم", url=channel_link_2)
        )
        markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
        
        channels_text = f"1️⃣ {channel_1[0]}\n2️⃣ {channel_2[0]}"
        force_msg = config.FORCE_JOIN_MESSAGE.format(channels=channels_text)
        
        bot.reply_to(message, force_msg, reply_markup=markup, parse_mode="Markdown")
        return
    
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

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    user_id = call.from_user.id
    
    if db.check_force_join(user_id):
        bot.answer_callback_query(call.id, "✅ عضویت در هر دو کانال تأیید شد!")
        bot.edit_message_text("✅ عضویت شما تأیید شد. حالا می‌تونید از ربات استفاده کنید.", call.message.chat.id, call.message.message_id)
        
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
        bot.send_message(user_id, welcome_text, parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ شما هنوز در هر دو کانال عضو نشده‌اید!", show_alert=True)

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
👑 ادمین‌ها: {stats['total_admins']}
📢 عضو کانال اول: {stats['joined_channel_1']}
📢 عضو کانال دوم: {stats['joined_channel_2']}
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
        text = f"""
📊 **آمار کامل**

👥 **کاربران:**
• کل: {stats['total_users']}
• فعال امروز: {stats['today_active']}
• بلاک شده: {stats['blocked_users']}
• ادمین‌ها: {stats['total_admins']}
• عضو کانال اول: {stats['joined_channel_1']}
• عضو کانال دوم: {stats['joined_channel_2']}

📥 **دانلودها:**
• کل: {stats['total_downloads']}
• امروز: {stats['today_downloads']}

🟢 **وضعیت:** {'روشن' if db.is_bot_on() else 'خاموش'}
        """
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif action == "broadcast":
        bot.edit_message_text("📢 **پیام همگانی جدید**\n\nلطفاً متن پیام رو بفرست:", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, broadcast_handler)

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

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    url = message.text.strip()
    user_id = message.from_user.id
    
    db.add_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    # بررسی عضویت اجباری در دو کانال
    if not db.check_force_join(user_id):
        channel_1 = db.execute("SELECT value FROM settings WHERE key = 'force_join_channel_1'", fetch_one=True)
        channel_2 = db.execute("SELECT value FROM settings WHERE key = 'force_join_channel_2'", fetch_one=True)
        
        channel_link_1 = f"https://t.me/{channel_1[0].replace('@', '')}" if channel_1 else ""
        channel_link_2 = f"https://t.me/{channel_2[0].replace('@', '')}" if channel_2 else ""
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📢 کانال اول", url=channel_link_1),
            InlineKeyboardButton("📢 کانال دوم", url=channel_link_2)
        )
        markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
        
        channels_text = f"1️⃣ {channel_1[0]}\n2️⃣ {channel_2[0]}"
        force_msg = config.FORCE_JOIN_MESSAGE.format(channels=channels_text)
        
        bot.reply_to(message, force_msg, reply_markup=markup, parse_mode="Markdown")
        return
    
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
            markup.add(
                InlineKeyboardButton("🎵 MP3 (صوت)", callback_data=f"dl_mp3_{url}"),
                InlineKeyboardButton("🎬 MP4 (ویدیو)", callback_data=f"dl_mp4_{url}"),
                InlineKeyboardButton("📥 بهترین کیفیت", callback_data=f"dl_best_{url}")
            )
            
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

@app.route('/')
def home():
    return """
    <html dir="rtl">
    <head><title>ربات دانلود</title></head>
    <body style="font-family: Tahoma; text-align: center; padding: 50px;">
        <h1>🤖 ربات دانلود از همه سایت‌ها</h1>
        <p>ربات با موفقیت اجرا شد!</p>
        <p>برای استفاده به تلگرام بروید و /start بزنید.</p>
    </body>
    </html>
    """

# ================= تنظیم Webhook =================
def setup_webhook():
    try:
        bot.remove_webhook()
        time.sleep(1)
        success = bot.set_webhook(url=config.WEBHOOK_URL)
        
        if success:
            logger.info(f"✅ Webhook تنظیم شد: {config.WEBHOOK_URL}")
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
    logger.info(f"📢 عضویت اجباری در: {config.FORCE_JOIN_CHANNEL_1} و {config.FORCE_JOIN_CHANNEL_2}")
    
    if setup_webhook():
        logger.info("✅ Webhook با موفقیت تنظیم شد")
    else:
        logger.warning("⚠️ خطا در تنظیم Webhook - ادامه با polling")
    
    logger.info(f"🚀 اجرا روی پورت {config.WEBHOOK_PORT}")
    app.run(host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT, debug=config.DEBUG, threaded=True)
