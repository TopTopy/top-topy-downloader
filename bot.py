# -*- coding: utf-8 -*-
import os
import threading
import time
import re
import random
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3
import requests
from urllib.parse import urlparse, urljoin
from flask import Flask, request

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
    if "facebook" in url or "fb.com" in url:
        return "Facebook"
    if "pinterest" in url or "pin.it" in url:
        return "Pinterest"
    return "Other"

# ================= تابع تشخیص و دنبال کردن لینک‌های کوتاه =================
def resolve_short_url(url):
    try:
        short_domains = ['pin.it', 'bit.ly', 'tinyurl.com', 'short.link', 't.co', 'youtu.be']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10)
            return response.url
        return url
    except Exception as e:
        print(f"خطا در تشخیص لینک کوتاه: {e}")
        return url

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
            ("bot_status", "ON"),
            ("total_users", "0"),
            ("total_downloads", "0"),
            ("total_groups", "0"),
            ("group_mode", "ON"),
            ("private_mode", "ON")
        ]
        for k, v in defaults:
            self.cursor.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id,is_admin) VALUES(?,1)", (ADMIN_ID,))
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
        try:
            self.conn.close()
        except:
            pass
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()

    def add_user(self, user_id, username, first_name):
        now = datetime.now()
        self.cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE users SET last_use=?, username=?, first_name=? WHERE user_id=?",
                                (now, username, first_name, user_id))
        else:
            self.cursor.execute("""
            INSERT INTO users(user_id,username,first_name,joined_date,last_use)
            VALUES(?,?,?,?,?)
            """, (user_id, username, first_name, now, now))
            total = int(self.get_setting("total_users"))
            self.set_setting("total_users", str(total + 1))
        self.conn.commit()

    def add_group(self, chat_id, title):
        now = datetime.now()
        self.cursor.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE groups SET last_active=?, title=? WHERE chat_id=?", (now, title, chat_id))
        else:
            self.cursor.execute("""
            INSERT INTO groups(chat_id,title,added_date,last_active)
            VALUES(?,?,?,?)
            """, (chat_id, title, now, now))
            total = int(self.get_setting("total_groups"))
            self.set_setting("total_groups", str(total + 1))
        self.conn.commit()

    def add_download(self, user_id, chat_id, url, format_type, size, source, platform):
        now = datetime.now()
        self.cursor.execute("""
        INSERT INTO downloads(user_id,chat_id,url,format,size,timestamp,source,platform)
        VALUES(?,?,?,?,?,?,?,?)
        """, (user_id, chat_id, url, format_type, size, now, source, platform))
        self.cursor.execute("UPDATE users SET download_count=download_count+1 WHERE user_id=?", (user_id,))
        total = int(self.get_setting("total_downloads"))
        self.set_setting("total_downloads", str(total + 1))
        self.conn.commit()

    def get_setting(self, key):
        self.cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = self.cursor.fetchone()
        return r[0] if r else "0"

    def set_setting(self, key, val):
        self.cursor.execute("UPDATE settings SET value=? WHERE key=?", (val, key))
        self.conn.commit()

    def is_blocked(self, user_id):
        self.cursor.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,))
        r = self.cursor.fetchone()
        return r and r[0] == 1

    def block_user(self, user_id):
        self.cursor.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def unblock_user(self, user_id):
        self.cursor.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def check_membership(self, user_id):
        try:
            for username, _ in REQUIRED_CHANNELS:
                member = bot.get_chat_member(username, user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    return False
            return True
        except Exception as e:
            print(f"خطا در بررسی عضویت: {e}")
            return False

    def get_stats(self):
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute("SELECT COUNT(*),SUM(download_count) FROM users")
        total_users, total_downloads = self.cursor.fetchone()
        self.cursor.execute("SELECT COUNT(*) FROM groups")
        total_groups = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE date(last_use)=date('now')")
        active_today = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM groups WHERE date(last_active)=date('now')")
        active_groups = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1")
        blocked = self.cursor.fetchone()[0]
        return {
            "total_users": total_users or 0,
            "total_downloads": total_downloads or 0,
            "total_groups": total_groups or 0,
            "active_today": active_today or 0,
            "active_groups": active_groups or 0,
            "blocked": blocked or 0,
            "bot_status": self.get_setting("bot_status"),
            "group_mode": self.get_setting("group_mode"),
            "private_mode": self.get_setting("private_mode")
        }

    def get_users(self, limit=20):
        self.cursor.execute("""
        SELECT user_id, username, first_name, download_count, is_blocked
        FROM users ORDER BY last_use DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

    def get_groups(self, limit=20):
        self.cursor.execute("""
        SELECT chat_id, title, added_date, last_active, is_active
        FROM groups ORDER BY last_active DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

    def get_recent_downloads(self, limit=20):
        self.cursor.execute("""
        SELECT user_id, url, platform, timestamp FROM downloads ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

# ================= ربات =================
db = Database()
bot = telebot.TeleBot(TOKEN)

# ================= تابع بررسی عضویت با دکمه =================
def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ عضویت را بررسی کن", callback_data="check_join"))
    return markup

# ================= تابع دانلود با پشتیبانی قوی از Pinterest =================
def download_video(url, chat_id, user_id, is_group=False):
    try:
        original_url = url
        resolved_url = resolve_short_url(url)
        if resolved_url != original_url:
            bot.send_message(chat_id, f"🔗 **لینک کوتاه تشخیص داده شد.**\nدر حال هدایت به آدرس اصلی...", parse_mode="Markdown")
            url = resolved_url

        platform = detect_platform(url)
        is_audio = any(word in url.lower() for word in ['mp3', 'audio', 'music', 'sound'])

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": f"{DOWNLOAD_PATH}/%(title)s.%(ext)s",
            "ignoreerrors": True,
            "extract_flat": False,
        }

        if platform == "Pinterest":
            bot.send_message(chat_id, "🖼️ **در حال دریافت از Pinterest...**", parse_mode="Markdown")
            
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ]
            
            ydl_opts.update({
                "format": "best",
                "force_generic_extractor": True,
                "socket_timeout": 30,
                "retries": 5,
                "fragment_retries": 5,
                "headers": {
                    "User-Agent": random.choice(user_agents),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.pinterest.com/",
                }
            })

        elif is_audio:
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            ydl_opts["format"] = "best[filesize<300M]/best"

        msg = bot.send_message(chat_id, f"⏳ **در حال دریافت از {platform} ...**", parse_mode="Markdown")

        info = None
        methods = [
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False),
            lambda: yt_dlp.YoutubeDL({"quiet": True, "format": "best"}).extract_info(url, download=False),
            lambda: yt_dlp.YoutubeDL({"quiet": True, "force_generic_extractor": True}).extract_info(url, download=False)
        ]

        for i, method in enumerate(methods):
            try:
                bot.edit_message_text(f"⏳ **تلاش {i+1} از {len(methods)} ...**", chat_id, msg.message_id, parse_mode="Markdown")
                info = method()
                if info:
                    bot.edit_message_text(f"✅ **اطلاعات دریافت شد**", chat_id, msg.message_id, parse_mode="Markdown")
                    break
            except:
                continue

        if info is None:
            bot.edit_message_text("❌ **خطا در دریافت اطلاعات**", chat_id, msg.message_id, parse_mode="Markdown")
            return

        bot.edit_message_text(f"⏳ **در حال دانلود...**", chat_id, msg.message_id, parse_mode="Markdown")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            bot.edit_message_text("❌ **خطا در دانلود فایل**", chat_id, msg.message_id, parse_mode="Markdown")
            return

        title = "file"
        if isinstance(info, dict):
            title = clean_filename(info.get("title", "file"))
        
        if not title or title == "file":
            title = clean_filename(url.split('/')[-1][:50])

        filename = None
        for f in os.listdir(DOWNLOAD_PATH):
            if title in f:
                filename = os.path.join(DOWNLOAD_PATH, f)
                break

        if not filename or not os.path.exists(filename):
            files = sorted(os.listdir(DOWNLOAD_PATH), key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_PATH, x)))
            if files:
                filename = os.path.join(DOWNLOAD_PATH, files[-1])

        if not filename or not os.path.exists(filename):
            bot.edit_message_text("❌ **فایل پیدا نشد**", chat_id, msg.message_id, parse_mode="Markdown")
            return

        size = os.path.getsize(filename)
        if size > MAX_FILE_SIZE:
            os.remove(filename)
            bot.edit_message_text("❌ **حجم فایل بیشتر از ۳۰۰MB**", chat_id, msg.message_id, parse_mode="Markdown")
            return

        bot.edit_message_text("📤 **در حال آپلود ...**", chat_id, msg.message_id, parse_mode="Markdown")

        with open(filename, "rb") as f:
            if filename.endswith((".mp4", ".mkv", ".webm")):
                bot.send_video(chat_id, f, caption=f"✅ **{title}**", parse_mode="Markdown")
                format_type = "video"
            elif filename.endswith(".mp3"):
                bot.send_audio(chat_id, f, caption=f"✅ **{title}**", parse_mode="Markdown")
                format_type = "audio"
            elif filename.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                bot.send_photo(chat_id, f, caption=f"✅ **{title}**", parse_mode="Markdown")
                format_type = "photo"
            else:
                bot.send_document(chat_id, f, caption=f"✅ **{title}**", parse_mode="Markdown")
                format_type = "file"

        source = "group" if is_group else "private"
        db.add_download(user_id, chat_id, url, format_type, size, source, platform)
        os.remove(filename)
        bot.delete_message(chat_id, msg.message_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")

# ================= پنل ادمین کامل =================
@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ شما دسترسی به پنل ادمین ندارید!")
        return
    
    stats = db.get_stats()
    
    text = f"👑 **پنل مدیریت** 👑\n\n"
    text += f"📊 **آمار کلی:**\n"
    text += f"👥 کاربران کل: {stats['total_users']}\n"
    text += f"📥 دانلودهای کل: {stats['total_downloads']}\n"
    text += f"👥 گروه‌های کل: {stats['total_groups']}\n"
    text += f"🟢 کاربران فعال امروز: {stats['active_today']}\n"
    text += f"👥 گروه‌های فعال امروز: {stats['active_groups']}\n"
    text += f"🔒 کاربران بلاک شده: {stats['blocked']}\n"
    text += f"🟢 وضعیت ربات: {'روشن' if stats['bot_status'] == 'ON' else 'خاموش'}\n\n"
    text += f"🔽 از دکمه‌های زیر استفاده کنید:"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 روشن/خاموش", callback_data="admin_toggle"),
        InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
        InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users"),
        InlineKeyboardButton("📥 لیست دانلودها", callback_data="admin_downloads"),
        InlineKeyboardButton("👥 لیست گروه‌ها", callback_data="admin_groups"),
        InlineKeyboardButton("🔒 بلاک کاربر", callback_data="admin_block"),
        InlineKeyboardButton("🔓 آنبلاک کاربر", callback_data="admin_unblock"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔄 ریست آمار", callback_data="admin_reset"),
        InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")
    )
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید")
        return

    action = call.data.replace('admin_', '')

    if action == "toggle":
        current = db.get_setting("bot_status")
        new = "OFF" if current == "ON" else "ON"
        db.set_setting("bot_status", new)
        bot.answer_callback_query(call.id, f"✅ وضعیت به {new} تغییر کرد")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        admin_command(call.message)
    
    elif action == "stats":
        stats = db.get_stats()
        text = f"📊 **آمار کامل**\n\n"
        text += f"👥 کل کاربران: {stats['total_users']}\n"
        text += f"📥 کل دانلودها: {stats['total_downloads']}\n"
        text += f"👥 کل گروه‌ها: {stats['total_groups']}\n"
        text += f"🟢 کاربران فعال امروز: {stats['active_today']}\n"
        text += f"👥 گروه‌های فعال امروز: {stats['active_groups']}\n"
        text += f"🔒 کاربران بلاک شده: {stats['blocked']}\n"
        text += f"🟢 وضعیت ربات: {'روشن' if stats['bot_status'] == 'ON' else 'خاموش'}\n"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "users":
        users = db.get_users(20)
        text = "👥 **۲۰ کاربر آخر:**\n\n"
        for u in users:
            status = "🔒" if u[4] else "✅"
            name = u[2] or u[1] or 'ناشناس'
            text += f"{status} `{u[0]}` | {name} | دانلود: {u[3]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "downloads":
        downloads = db.get_recent_downloads(20)
        text = "📥 **۲۰ دانلود آخر:**\n\n"
        for d in downloads:
            text += f"👤 `{d[0]}` | {d[2]} | {d[3][:16]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "groups":
        groups = db.get_groups(20)
        text = "👥 **۲۰ گروه آخر:**\n\n"
        for g in groups:
            status = "✅" if g[4] else "❌"
            text += f"{status} `{g[0]}` | {g[1][:30]} | {g[3][:16]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "block":
        bot.edit_message_text("🔒 **آیدی عددی کاربر مورد نظر برای بلاک را بفرستید:**", 
                            call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, block_user_handler)
    
    elif action == "unblock":
        bot.edit_message_text("🔓 **آیدی عددی کاربر مورد نظر برای آنبلاک را بفرستید:**", 
                            call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, unblock_user_handler)
    
    elif action == "broadcast":
        bot.edit_message_text("📢 **متن پیام همگانی را بفرستید:**", 
                            call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.register_next_step_handler(call.message, broadcast_handler)
    
    elif action == "reset":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ بله، ریست کن", callback_data="admin_reset_confirm"),
            InlineKeyboardButton("❌ خیر، منصرف شدم", callback_data="admin_back")
        )
        bot.edit_message_text("⚠️ **آیا از ریست آمار اطمینان دارید؟**\nاین عمل غیرقابل بازگشت است!", 
                            call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "reset_confirm":
        db.cursor.execute("DELETE FROM downloads")
        db.cursor.execute("UPDATE settings SET value='0' WHERE key IN ('total_downloads', 'total_users', 'total_groups')")
        db.conn.commit()
        bot.answer_callback_query(call.id, "✅ آمار با موفقیت ریست شد")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        admin_command(call.message)
    
    elif action == "back":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        admin_command(call.message)
    
    elif action == "close":
        bot.delete_message(call.message.chat.id, call.message.message_id)

def block_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.block_user(user_id)
        bot.reply_to(message, f"✅ کاربر `{user_id}` با موفقیت بلاک شد.", parse_mode="Markdown")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: لطفاً یک آیدی عددی معتبر بفرستید.")

def unblock_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.unblock_user(user_id)
        bot.reply_to(message, f"✅ کاربر `{user_id}` با موفقیت آنبلاک شد.", parse_mode="Markdown")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: لطفاً یک آیدی عددی معتبر بفرستید.")

def broadcast_handler(message):
    msg_text = message.text
    users = db.get_users(1000)
    
    status_msg = bot.reply_to(message, "📤 **در حال ارسال پیام همگانی...**", parse_mode="Markdown")
    
    sent = 0
    failed = 0
    
    for user in users:
        if not user[4]:
            try:
                bot.send_message(user[0], f"📢 **پیام همگانی**\n\n{msg_text}", parse_mode="Markdown")
                sent += 1
            except:
                failed += 1
            time.sleep(0.05)
    
    bot.edit_message_text(f"✅ **نتیجه ارسال همگانی**\n\n📤 ارسال شده: {sent}\n❌ ناموفق: {failed}", 
                        status_msg.chat.id, status_msg.message_id, parse_mode="Markdown")
    admin_command(message)

# ================= تلگرام =================
@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if not db.check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    welcome_text = (
        f"🎬 سلام {message.from_user.first_name or message.from_user.username}!\n\n"
        "من ربات **𝘁𝗼𝗽 𝘁𝗼𝗽𝘆 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗿** هستم 🤖\n"
        "می‌تونی منو به گروه خودت اضافه کنی یا مستقیم به من لینک بدی تا هر چیزی رو دانلود کنم!\n\n"
        "✅ **پشتیبانی از:**\n"
        "• YouTube | TikTok | Instagram\n"
        "• Twitter | Facebook | Pinterest\n"
        "• و بیش از ۱۰۰۰ سایت دیگر\n\n"
        "✅ **لینک‌های کوتاه:**\n"
        "• پشتیبانی کامل از pin.it و سایر لینک‌های کوتاه\n\n"
        "✅ **حجم مجاز:** ۳۰۰ مگابایت\n\n"
        "📌 فقط کافیه لینک رو برای من بفرستی!"
    )
    bot.reply_to(message, welcome_text)

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if db.check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.edit_message_text(
            "✅ عضویت شما تأیید شد. حالا می‌تونید از ربات استفاده کنید.",
            call.message.chat.id,
            call.message.message_id
        )
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ شما هنوز عضو نشده‌اید!", show_alert=True)

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    if not message.text.startswith(('http://', 'https://')):
        return

    if db.get_setting("bot_status") == "OFF":
        bot.reply_to(message, "⛔ ربات خاموش است")
        return
    if db.is_blocked(message.from_user.id):
        bot.reply_to(message, "⛔ شما بلاک هستید")
        return

    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if message.chat.type in ["group", "supergroup"]:
        db.add_group(message.chat.id, message.chat.title)

    if not db.check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    urls = extract_urls(message.text)
    if not urls:
        return
    url = urls[0]
    bot.reply_to(message, "✅ لینک دریافت شد، شروع دانلود...")
    threading.Thread(
        target=download_video,
        args=(url, message.chat.id, message.from_user.id, message.chat.type in ["group", "supergroup"]),
        daemon=True
    ).start()

# ================= وب‌هوک =================
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def home():
    return "ربات فعال است - از دستور /admin استفاده کنید"

# ================= اجرا =================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("🚀 ربات 𝘁𝗼𝗽 𝘁𝗼𝗽𝘆 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗿 آماده است")
    print(f"🌐 Webhook: {WEBHOOK_URL}")
    print("✅ پنل ادمین فعال است - با دستور /admin")
    app.run(host="0.0.0.0", port=PORT)
