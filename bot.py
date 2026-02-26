# -*- coding: utf-8 -*-
import os
import threading
import time
import re
import random
import json
import subprocess
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import sqlite3
import requests
from urllib.parse import urlparse, urljoin
from flask import Flask, request

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

def check_dependencies():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True)
        print("✅ ffmpeg نصب است")
    except:
        print("⚠️ ffmpeg نصب نیست")

check_dependencies()

def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def detect_platform(url):
    url = url.lower()
    if "youtube" in url or "youtu.be" in url:
        return "YouTube"
    if "tiktok" in url or "vt.tiktok" in url:
        return "TikTok"
    if "instagram" in url:
        return "Instagram"
    if "twitter" in url or "x.com" in url:
        return "Twitter"
    if "facebook" in url or "fb.com" in url:
        return "Facebook"
    if "pinterest" in url or "pin.it" in url:
        return "Pinterest"
    if "reddit" in url:
        return "Reddit"
    if "twitch" in url:
        return "Twitch"
    if "vimeo" in url:
        return "Vimeo"
    if "dailymotion" in url:
        return "Dailymotion"
    if "soundcloud" in url:
        return "SoundCloud"
    if "spotify" in url:
        return "Spotify"
    if "aparat" in url:
        return "Aparat"
    if "namasha" in url:
        return "Namasha"
    if "telewebion" in url:
        return "Telewebion"
    return "Other"

def resolve_short_url(url):
    try:
        short_domains = ['pin.it', 'bit.ly', 'tinyurl.com', 'short.link', 't.co', 'youtu.be', 'vt.tiktok.com']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10)
            return response.url
        return url
    except Exception as e:
        print(f"خطا در تشخیص لینک کوتاه: {e}")
        return url

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

db = Database()
bot = telebot.TeleBot(TOKEN)

def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ عضویت را بررسی کن", callback_data="check_join"))
    return markup

def download_tiktok(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "🎵 **در حال دریافت از تیک‌تاک...**", parse_mode="Markdown")
        try:
            api_url = "https://tikwm.com/api/"
            data = {"url": url, "hd": 1}
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.post(api_url, data=data, headers=headers, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("data"):
                    download_url = result["data"].get("play") or result["data"].get("hdplay")
                    if download_url:
                        file_response = requests.get(download_url, timeout=60)
                        if file_response.status_code == 200:
                            filename = f"{DOWNLOAD_PATH}/tiktok_{int(time.time())}.mp4"
                            with open(filename, "wb") as f:
                                f.write(file_response.content)
                            with open(filename, "rb") as f:
                                bot.send_video(chat_id, f, caption=f"✅ **دانلود از تیک‌تاک**")
                            db.add_download(user_id, chat_id, url, "video", len(file_response.content), 
                                          "group" if is_group else "private", "TikTok")
                            os.remove(filename)
                            return True
        except:
            pass
        bot.send_message(chat_id, "❌ **خطا در دانلود از تیک‌تاک**", parse_mode="Markdown")
        return False
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

def download_instagram(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "📸 **در حال دریافت از اینستاگرام...**", parse_mode="Markdown")
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": f"{DOWNLOAD_PATH}/%(title)s.%(ext)s",
            "format": "best",
            "force_generic_extractor": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = clean_filename(info.get("title", "instagram_video"))
                for f in os.listdir(DOWNLOAD_PATH):
                    if title in f:
                        filename = os.path.join(DOWNLOAD_PATH, f)
                        with open(filename, "rb") as file:
                            bot.send_video(chat_id, file, caption=f"✅ **{title}**")
                        size = os.path.getsize(filename)
                        db.add_download(user_id, chat_id, url, "video", size, 
                                      "group" if is_group else "private", "Instagram")
                        os.remove(filename)
                        return True
        return False
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

def download_pinterest(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "🖼️ **در حال دریافت از Pinterest...**", parse_mode="Markdown")
        if "pin.it" in url:
            response = requests.head(url, allow_redirects=True)
            url = response.url
        pin_id = None
        if "/pin/" in url:
            pin_id = url.split("/pin/")[-1].split("/")[0].split("?")[0]
        if pin_id:
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and len(data["data"]) > 0:
                    pin_data = data["data"][0]
                    if pin_data.get("images"):
                        img_url = pin_data["images"].get("orig", {}).get("url")
                        if img_url:
                            img_response = requests.get(img_url, headers=headers)
                            if img_response.status_code == 200:
                                filename = f"{DOWNLOAD_PATH}/pinterest_{pin_id}.jpg"
                                with open(filename, "wb") as f:
                                    f.write(img_response.content)
                                with open(filename, "rb") as f:
                                    bot.send_photo(chat_id, f, caption=f"✅ **عکس پینترست**")
                                db.add_download(user_id, chat_id, url, "photo", len(img_response.content), 
                                              "group" if is_group else "private", "Pinterest")
                                os.remove(filename)
                                return True
        return False
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

def download_video(url, chat_id, user_id, is_group=False):
    try:
        platform = detect_platform(url)
        if platform == "TikTok":
            download_tiktok(url, chat_id, user_id, is_group)
            return
        if platform == "Instagram":
            download_instagram(url, chat_id, user_id, is_group)
            return
        if platform == "Pinterest":
            download_pinterest(url, chat_id, user_id, is_group)
            return
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": f"{DOWNLOAD_PATH}/%(title)s.%(ext)s",
            "ignoreerrors": True,
            "format": "best[filesize<300M]/best",
            "socket_timeout": 30,
            "retries": 3,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            }
        }
        msg = bot.send_message(chat_id, f"⏳ **در حال دریافت از {platform} ...**", parse_mode="Markdown")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if not info:
            bot.edit_message_text("❌ **خطا در دریافت اطلاعات**", chat_id, msg.message_id, parse_mode="Markdown")
            return
        title = clean_filename(info.get("title", "file"))
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
                bot.send_video(chat_id, f, caption=f"✅ **{title}**")
                format_type = "video"
            elif filename.endswith(".mp3"):
                bot.send_audio(chat_id, f, caption=f"✅ **{title}**")
                format_type = "audio"
            elif filename.endswith((".jpg", ".jpeg", ".png", ".gif")):
                bot.send_photo(chat_id, f, caption=f"✅ **{title}**")
                format_type = "photo"
            else:
                bot.send_document(chat_id, f, caption=f"✅ **{title}**")
                format_type = "file"
        db.add_download(user_id, chat_id, url, format_type, size, 
                       "group" if is_group else "private", platform)
        os.remove(filename)
        bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")

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
    text += f"🔒 کاربران بلاک شده: {stats['blocked']}\n"
    text += f"🟢 وضعیت ربات: {'روشن' if stats['bot_status'] == 'ON' else 'خاموش'}\n\n"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 روشن/خاموش", callback_data="admin_toggle"),
        InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
        InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users"),
        InlineKeyboardButton("📥 لیست دانلودها", callback_data="admin_downloads"),
        InlineKeyboardButton("🔒 بلاک کاربر", callback_data="admin_block"),
        InlineKeyboardButton("🔓 آنبلاک کاربر", callback_data="admin_unblock"),
        InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔄 ریست آمار", callback_data="admin_reset"),
        InlineKeyboardButton("❌ بستن", callback_data="admin_close")
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
        text += f"🟢 فعال امروز: {stats['active_today']}\n"
        text += f"🔒 بلاک شده: {stats['blocked']}"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif action == "users":
        users = db.get_users(10)
        text = "👥 **۱۰ کاربر آخر:**\n\n"
        for u in users:
            status = "🔒" if u[4] else "✅"
            name = u[2] or u[1] or 'ناشناس'
            text += f"{status} `{u[0]}` | {name} | دانلود: {u[3]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif action == "downloads":
        downloads = db.get_recent_downloads(10)
        text = "📥 **۱۰ دانلود آخر:**\n\n"
        for d in downloads:
            text += f"👤 `{d[0]}` | {d[2]} | {d[3][:16]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif action == "block":
        msg = bot.send_message(call.message.chat.id, "🔒 **آیدی کاربر را بفرستید:**")
        bot.register_next_step_handler(msg, block_user_handler)
    elif action == "unblock":
        msg = bot.send_message(call.message.chat.id, "🔓 **آیدی کاربر را بفرستید:**")
        bot.register_next_step_handler(msg, unblock_user_handler)
    elif action == "broadcast":
        msg = bot.send_message(call.message.chat.id, "📢 **متن پیام را بفرستید:**")
        bot.register_next_step_handler(msg, broadcast_handler)
    elif action == "reset":
        db.cursor.execute("DELETE FROM downloads")
        db.cursor.execute("UPDATE settings SET value='0' WHERE key IN ('total_downloads', 'total_users', 'total_groups')")
        db.conn.commit()
        bot.answer_callback_query(call.id, "✅ آمار ریست شد")
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
        bot.reply_to(message, f"✅ کاربر `{user_id}` بلاک شد.")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: آیدی نامعتبر")

def unblock_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.unblock_user(user_id)
        bot.reply_to(message, f"✅ کاربر `{user_id}` آنبلاک شد.")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: آیدی نامعتبر")

def broadcast_handler(message):
    msg_text = message.text
    users = db.get_users(1000)
    sent = 0
    for user in users:
        if not user[4]:
            try:
                bot.send_message(user[0], f"📢 **پیام همگانی**\n\n{msg_text}")
                sent += 1
            except:
                pass
            time.sleep(0.05)
    bot.reply_to(message, f"✅ ارسال به {sent} کاربر")

@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if not db.check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، در کانال‌ها عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return
    welcome_text = (
        f"🎬 سلام {message.from_user.first_name or message.from_user.username}!\n\n"
        "ربات **𝘁𝗼𝗽 𝘁𝗼𝗽𝘆 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗲𝗿** 🤖\n"
        "از همه سایت‌ها دانلود میکنم!\n\n"
        "✅ پشتیبانی: YouTube | TikTok | Instagram\n"
        "✅ Pinterest | Twitter | Facebook\n"
        "✅ تمام سایت‌های فارسی\n"
        "✅ حجم: ۳۰۰ مگابایت\n\n"
        "📌 لینک رو بفرست!"
    )
    bot.reply_to(message, welcome_text)

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if db.check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.edit_message_text("✅ عضویت تأیید شد.", call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ عضو نشده‌اید!", show_alert=True)

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
            "🔒 **برای استفاده از ربات، در کانال‌ها عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return
    urls = extract_urls(message.text)
    if not urls:
        return
    url = urls[0]
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**")
        url = resolved_url
    bot.reply_to(message, "✅ لینک دریافت شد...")
    threading.Thread(
        target=download_video,
        args=(url, message.chat.id, message.from_user.id, message.chat.type in ["group", "supergroup"]),
        daemon=True
    ).start()

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def home():
    return "ربات فعال است - /admin"

if __name__ == "__main__":
    print("🚀 راه‌اندازی ربات...")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("✅ Webhook تنظیم شد")
    print("✅ پنل ادمین فعال است")
    app.run(host="0.0.0.0", port=PORT)
