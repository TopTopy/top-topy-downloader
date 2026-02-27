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

def is_instagram_url(url):
    """بررسی اینکه آیا لینک اینستاگرام است"""
    url = url.lower()
    instagram_domains = ['instagram.com', 'instagr.am']
    for domain in instagram_domains:
        if domain in url:
            return True
    return False

# ================= تابع تشخیص و دنبال کردن لینک‌های کوتاه =================
def resolve_short_url(url):
    try:
        short_domains = ['pin.it', 'bit.ly', 'tinyurl.com', 'short.link', 't.co', 'youtu.be', 'vt.tiktok.com', 
                        'rb.gy', 'shorturl.at', 'ow.ly', 'is.gd', 'buff.ly', 'lnkd.in', 'fb.watch', 'instagr.am']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            return response.url
        return url
    except Exception as e:
        print(f"خطا در تشخیص لینک کوتاه: {e}")
        return url

# ================= سیستم دانلود اینستاگرام =================
class InstagramDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        
    def setup_session(self):
        """تنظیمات پیشرفته برای سشن"""
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })
    
    def _download_file(self, url, prefix):
        """دانلود فایل از لینک مستقیم"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.instagram.com/",
            }
            
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            
            if response.status_code == 200:
                # تشخیص پسوند فایل
                content_type = response.headers.get('content-type', '')
                if 'video' in content_type:
                    ext = '.mp4'
                elif 'image' in content_type:
                    ext = '.jpg'
                else:
                    # استخراج از URL
                    ext = os.path.splitext(url.split('?')[0])[1]
                    if not ext:
                        ext = '.mp4'
                
                filename = f"{DOWNLOAD_PATH}/instagram_{prefix}_{int(time.time())}{ext}"
                
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                return {
                    'filename': filename,
                    'size': os.path.getsize(filename),
                    'type': prefix
                }
                
        except Exception as e:
            print(f"خطا در دانلود فایل: {e}")
            return None

    # ========== روش‌های دانلود اینستاگرام ==========
    def method_1_api_cobalt(self, url):
        """روش 1: API cobalt.tools برای اینستاگرام"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {
                "url": url, 
                "downloadMode": "auto",
                "videoQuality": "max",
                "audioFormat": "best",
            }
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "cobalt")
        except:
            return None
    
    def method_2_saveinsta(self, url):
        """روش 2: استفاده از SaveInsta.app"""
        try:
            api_url = "https://saveinsta.app/api/ajaxSearch"
            data = {"q": url, "t": "media"}
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest"
            }
            
            response = requests.post(api_url, data=data, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "saveinsta")
        except:
            return None
    
    def method_3_igdownloader(self, url):
        """روش 3: استفاده از IGDownloader"""
        try:
            api_url = "https://igdownloader.app/api/ajaxSearch"
            data = {"q": url, "t": "media"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "igdownloader")
        except:
            return None
    
    def method_4_snapinsta(self, url):
        """روش 4: استفاده از SnapInsta"""
        try:
            api_url = "https://snapinsta.app/api/ajaxSearch"
            data = {"q": url, "t": "media"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "snapinsta")
        except:
            return None
    
    def method_5_ytdlp(self, url):
        """روش 5: yt-dlp برای اینستاگرام"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'format': 'best',
                'outtmpl': f'{DOWNLOAD_PATH}/instagram_ytdlp_%(title)s.%(ext)s',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    # پیدا کردن فایل دانلود شده
                    title = info.get('title', '')
                    files = os.listdir(DOWNLOAD_PATH)
                    for f in files:
                        if title in f:
                            filename = os.path.join(DOWNLOAD_PATH, f)
                            return {
                                'filename': filename,
                                'size': os.path.getsize(filename),
                                'type': 'ytdlp'
                            }
        except:
            return None
    
    def method_6_direct_extract(self, url):
        """روش 6: استخراج مستقیم از HTML صفحه"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            }
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                patterns = [
                    r'<meta property="og:video" content="([^"]+)"',
                    r'<meta property="og:image" content="([^"]+)"',
                    r'"video_url":"([^"]+)"',
                    r'"display_url":"([^"]+)"',
                    r'"src":"([^"]+\.mp4)"',
                    r'content="([^"]+\.mp4)"',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, response.text)
                    for media_url in matches:
                        media_url = media_url.replace('\\u0026', '&').replace('\\/', '/')
                        if media_url.startswith('//'):
                            media_url = 'https:' + media_url
                        if media_url.startswith(('http://', 'https://')):
                            return self._download_file(media_url, "direct")
        except:
            return None
    
    def download(self, url, chat_id, user_id, is_group=False, msg_id=None):
        """تابع اصلی دانلود اینستاگرام با ۶ روش"""
        
        methods = [
            ("cobalt.tools", self.method_1_api_cobalt),
            ("SaveInsta", self.method_2_saveinsta),
            ("IGDownloader", self.method_3_igdownloader),
            ("SnapInsta", self.method_4_snapinsta),
            ("yt-dlp", self.method_5_ytdlp),
            ("استخراج مستقیم", self.method_6_direct_extract),
        ]
        
        # به‌روزرسانی پیام
        if msg_id:
            try:
                bot.edit_message_text(
                    f"🔄 **در حال دانلود از اینستاگرام...**\n📡 {len(methods)} روش مختلف آماده شد",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        
        # امتحان همه روش‌ها
        for i, (method_name, method_func) in enumerate(methods, 1):
            try:
                if msg_id:
                    try:
                        bot.edit_message_text(
                            f"🔄 **اینستاگرام** - روش {i}/{len(methods)}: {method_name}...",
                            chat_id,
                            msg_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                result = method_func(url)
                
                if result and os.path.exists(result['filename']):
                    # بررسی حجم فایل
                    if result['size'] > MAX_FILE_SIZE:
                        os.remove(result['filename'])
                        continue
                    
                    # آپلود فایل
                    if msg_id:
                        try:
                            bot.edit_message_text(
                                f"📤 **در حال آپلود...**\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                                chat_id,
                                msg_id,
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                    
                    # ارسال فایل
                    with open(result['filename'], 'rb') as f:
                        if result['filename'].endswith(('.mp4', '.mkv', '.webm')):
                            bot.send_video(chat_id, f, caption=f"✅ **دانلود از اینستاگرام با {method_name}**")
                        elif result['filename'].endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            bot.send_photo(chat_id, f, caption=f"✅ **دانلود از اینستاگرام با {method_name}**")
                        else:
                            bot.send_document(chat_id, f, caption=f"✅ **دانلود از اینستاگرام با {method_name}**")
                    
                    # ثبت در دیتابیس
                    db.add_download(
                        user_id, chat_id, url,
                        result['type'], result['size'],
                        "group" if is_group else "private",
                        "Instagram"
                    )
                    
                    # پاک کردن فایل
                    os.remove(result['filename'])
                    
                    if msg_id:
                        try:
                            bot.edit_message_text(
                                f"✅ **دانلود از اینستاگرام با موفقیت انجام شد!**\n🔧 روش: {method_name}",
                                chat_id,
                                msg_id,
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                    
                    return True
                    
            except Exception as e:
                print(f"خطا در روش {method_name}: {e}")
                continue
        
        # اگر هیچ روشی جواب نداد
        if msg_id:
            try:
                bot.edit_message_text(
                    f"❌ **متأسفانه دانلود از اینستاگرام با مشکل مواجه شد**\n\n"
                    f"💡 **همه {len(methods)} روش امتحان شدند**\n"
                    f"• لینک را دوباره بررسی کنید\n"
                    f"• چند دقیقه بعد دوباره تلاش کنید\n"
                    f"🔄 **لینک:**\n"
                    f"`{url}`",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        
        return False

# ================= ایجاد نمونه از دانلودر اینستاگرام =================
instagram_downloader = InstagramDownloader()

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

# ================= تابع دانلود اینستاگرام =================
def download_instagram(url, chat_id, user_id, is_group=False):
    try:
        # ارسال پیام شروع
        msg = bot.send_message(
            chat_id, 
            f"📸 **اینستاگرام**\n🔄 **فعال‌سازی موتور دانلود با ۶ روش...**", 
            parse_mode="Markdown"
        )
        
        # استفاده از دانلودر اینستاگرام
        return instagram_downloader.download(url, chat_id, user_id, is_group, msg.message_id)
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطای سیستمی:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

# ================= پنل ادمین =================
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
        text += f"🟢 وضعیت ربات: {'روشن' if stats['bot_status'] == 'ON' else 'خاموش'}"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "users":
        users = db.get_users(20)
        text = "👥 **۲۰ کاربر آخر:**\n\n"
        for u in users:
            status = "🔒" if u[4] else "✅"
            name = u[2] or u[1] or 'ناشناس'
            text += f"{status} `{u[0]}` | {name} | دانلود: {u[3]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "downloads":
        downloads = db.get_recent_downloads(20)
        text = "📥 **۲۰ دانلود آخر:**\n\n"
        for d in downloads:
            text += f"👤 `{d[0]}` | {d[2]} | {d[3][:16]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "groups":
        groups = db.get_groups(20)
        text = "👥 **۲۰ گروه آخر:**\n\n"
        for g in groups:
            status = "✅" if g[4] else "❌"
            text += f"{status} `{g[0]}` | {g[1][:30]} | {g[3][:16]}\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "block":
        msg = bot.send_message(call.message.chat.id, "🔒 **آیدی عددی کاربر مورد نظر برای بلاک را بفرستید:**")
        bot.register_next_step_handler(msg, block_user_handler)
    
    elif action == "unblock":
        msg = bot.send_message(call.message.chat.id, "🔓 **آیدی عددی کاربر مورد نظر برای آنبلاک را بفرستید:**")
        bot.register_next_step_handler(msg, unblock_user_handler)
    
    elif action == "broadcast":
        msg = bot.send_message(call.message.chat.id, "📢 **متن پیام همگانی را بفرستید:**")
        bot.register_next_step_handler(msg, broadcast_handler)
    
    elif action == "reset":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✅ بله", callback_data="admin_reset_confirm"),
            InlineKeyboardButton("❌ خیر", callback_data="admin_back")
        )
        bot.edit_message_text("⚠️ **آیا از ریست آمار اطمینان دارید؟**", 
                            call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif action == "reset_confirm":
        db.cursor.execute("DELETE FROM downloads")
        db.cursor.execute("UPDATE settings SET value='0' WHERE key IN ('total_downloads', 'total_users', 'total_groups')")
        db.conn.commit()
        bot.answer_callback_query(call.id, "✅ آمار ریست شد")
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
        bot.reply_to(message, f"✅ کاربر `{user_id}` بلاک شد.", parse_mode="Markdown")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: آیدی نامعتبر")

def unblock_user_handler(message):
    try:
        user_id = int(message.text.strip())
        db.unblock_user(user_id)
        bot.reply_to(message, f"✅ کاربر `{user_id}` آنبلاک شد.", parse_mode="Markdown")
        admin_command(message)
    except:
        bot.reply_to(message, "❌ خطا: آیدی نامعتبر")

def broadcast_handler(message):
    msg_text = message.text
    users = db.get_users(1000)
    
    status_msg = bot.reply_to(message, "📤 **در حال ارسال...**", parse_mode="Markdown")
    
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
    
    bot.edit_message_text(f"✅ ارسال شد: {sent}\n❌ ناموفق: {failed}", 
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
        f"📸 سلام {message.from_user.first_name or message.from_user.username}!\n\n"
        "من ربات **دانلودر اینستاگرام** هستم 🤖\n"
        "می‌تونم از اینستاگرام برات دانلود کنم!\n\n"
        "✅ **قابلیت‌ها:**\n"
        "• دانلود ویدیو و عکس از پست‌ها\n"
        "• دانلود ریلز (Reels)\n"
        "• دانلود استوری (Story)\n"
        "• دانلود IGTV\n\n"
        "✅ **۶ روش مختلف دانلود**\n"
        "✅ **حجم مجاز:** ۳۰۰ مگابایت\n\n"
        "📌 **فقط کافیه لینک اینستاگرام رو بفرستی!**"
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
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    urls = extract_urls(message.text)
    if not urls:
        return
    url = urls[0]
    
    # تشخیص لینک کوتاه
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**", parse_mode="Markdown")
        url = resolved_url
    
    # بررسی اینکه لینک اینستاگرام است
    if not is_instagram_url(url):
        bot.reply_to(message, "❌ **لطفاً فقط لینک اینستاگرام ارسال کنید.**\nاین ربات فقط از اینستاگرام پشتیبانی می‌کند.", parse_mode="Markdown")
        return
    
    bot.reply_to(message, "✅ **لینک اینستاگرام دریافت شد، شروع دانلود...**", parse_mode="Markdown")
    threading.Thread(
        target=download_instagram,
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
    return "ربات دانلودر اینستاگرام فعال است - فقط اینستاگرام"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*70)
    print("📸 راه‌اندازی ربات دانلودر اینستاگرام با ۶ روش...")
    print("="*70)
    print(f"👤 آیدی ادمین: {ADMIN_ID}")
    print(f"📁 مسیر دانلود: {DOWNLOAD_PATH}")
    print(f"📊 حجم مجاز: {MAX_FILE_SIZE/1024/1024}MB")
    print("✅ روش‌های دانلود اینستاگرام:")
    print("   1️⃣ cobalt.tools")
    print("   2️⃣ SaveInsta")
    print("   3️⃣ IGDownloader")
    print("   4️⃣ SnapInsta")
    print("   5️⃣ yt-dlp")
    print("   6️⃣ استخراج مستقیم از HTML")
    print("="*70)
    
    # پاکسازی پوشه دانلود
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except:
            pass
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    print("✅ Webhook تنظیم شد")
    print(f"🌐 Webhook: {WEBHOOK_URL}")
    print("✅ پنل ادمین با دستور /admin فعال است")
    print("✅ فقط اینستاگرام پشتیبانی می‌شود")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
