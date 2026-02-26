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

# ================= بررسی نصب بودن ffmpeg =================
def check_dependencies():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True)
        print("✅ ffmpeg نصب است")
    except:
        print("⚠️ ffmpeg نصب نیست - برای دانلود صوتی نیاز است")

check_dependencies()

# ================= ابزار =================
def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def detect_platform(url):
    url = url.lower()
    platforms = {
        'youtube': ['youtube.com', 'youtu.be'],
        'tiktok': ['tiktok.com', 'vt.tiktok.com'],
        'instagram': ['instagram.com'],
        'twitter': ['twitter.com', 'x.com'],
        'facebook': ['facebook.com', 'fb.com', 'fb.watch'],
        'pinterest': ['pinterest.com', 'pin.it'],
        'reddit': ['reddit.com'],
        'twitch': ['twitch.tv'],
        'vimeo': ['vimeo.com'],
        'dailymotion': ['dailymotion.com'],
        'soundcloud': ['soundcloud.com'],
        'spotify': ['spotify.com'],
        'aparat': ['aparat.com'],
        'telewebion': ['telewebion.com'],
        'filimo': ['filimo.com'],
        'namasha': ['namasha.com'],
        'clips': ['clips.ir'],
        'tamasha': ['tamasha.com'],
        'threads': ['threads.net'],
        'linkedin': ['linkedin.com'],
        'tumblr': ['tumblr.com'],
        'flickr': ['flickr.com'],
        'imgur': ['imgur.com'],
        'giphy': ['giphy.com'],
        'tenor': ['tenor.com'],
        '9gag': ['9gag.com'],
        'bitchute': ['bitchute.com'],
        'odysee': ['odysee.com'],
        'rumble': ['rumble.com'],
        'brighteon': ['brighteon.com'],
        'lbry': ['lbry.tv'],
        'minds': ['minds.com'],
        'gab': ['gab.com'],
        'gettr': ['gettr.com'],
        'parler': ['parler.com'],
        'telegram': ['t.me', 'telegram.me'],
        'whatsapp': ['whatsapp.com'],
        'snapchat': ['snapchat.com'],
        'likee': ['likee.com'],
        'sharechat': ['sharechat.com'],
        'moj': ['mojApp'],
        'chingsari': ['chingsari.com']
    }
    
    for platform, domains in platforms.items():
        for domain in domains:
            if domain in url:
                return platform.capitalize()
    return "Other"

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

# ================= تابع دانلود اختصاصی پینترست (نسخه فوق العاده) =================
def download_pinterest(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "🖼️ **در حال دریافت از Pinterest...**", parse_mode="Markdown")
        
        # تبدیل لینک کوتاه
        if "pin.it" in url:
            try:
                session = requests.Session()
                response = session.head(url, allow_redirects=True, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                })
                url = response.url
                bot.send_message(chat_id, f"🔗 لینک اصلی: `{url}`", parse_mode="Markdown")
            except:
                pass
        
        # روش 1: استخراج مستقیم از صفحه با Regex پیشرفته
        try:
            bot.send_message(chat_id, "🔄 **روش 1: استخراج مستقیم...**", parse_mode="Markdown")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                # الگوهای مختلف برای پیدا کردن عکس
                patterns = [
                    r'<meta property="og:image" content="([^"]+)"',
                    r'<meta name="twitter:image" content="([^"]+)"',
                    r'"image":"([^"]+)"',
                    r'"image_original_url":"([^"]+)"',
                    r'"image_url":"([^"]+)"',
                    r'"imgUrl":"([^"]+)"',
                    r'"image_src":"([^"]+)"',
                    r'<img[^>]+src="([^"]+)"[^>]*>',
                    r'data-test-id="pin-image"[^>]+src="([^"]+)"',
                    r'class="[^"]*pin-image[^"]*"[^>]+src="([^"]+)"',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, response.text, re.IGNORECASE)
                    if matches:
                        img_url = matches[0]
                        if isinstance(img_url, tuple):
                            img_url = img_url[0]
                        
                        # پاکسازی URL
                        img_url = img_url.replace('\\u002F', '/').replace('\\/', '/')
                        
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        elif img_url.startswith('/'):
                            img_url = 'https://www.pinterest.com' + img_url
                        
                        # دانلود عکس
                        img_response = requests.get(img_url, headers=headers, timeout=30, stream=True)
                        if img_response.status_code == 200:
                            # تشخیص فرمت
                            content_type = img_response.headers.get('content-type', '')
                            ext = 'jpg'
                            if 'png' in content_type:
                                ext = 'png'
                            elif 'gif' in content_type:
                                ext = 'gif'
                            elif 'webp' in content_type:
                                ext = 'webp'
                            
                            filename = f"{DOWNLOAD_PATH}/pinterest_{int(time.time())}.{ext}"
                            
                            with open(filename, "wb") as f:
                                for chunk in img_response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                            
                            size = os.path.getsize(filename)
                            if size <= MAX_FILE_SIZE:
                                with open(filename, "rb") as f:
                                    if ext == 'gif':
                                        bot.send_document(chat_id, f, caption=f"✅ **عکس پینترست**")
                                    else:
                                        bot.send_photo(chat_id, f, caption=f"✅ **عکس پینترست**")
                                
                                db.add_download(user_id, chat_id, url, "photo", size, 
                                              "group" if is_group else "private", "Pinterest")
                                os.remove(filename)
                                return True
        except Exception as e:
            print(f"خطا در روش استخراج مستقیم: {e}")
        
        # روش 2: استفاده از API جایگزین Pinterest (نسخه جدید)
        try:
            bot.send_message(chat_id, "🔄 **روش 2: API جایگزین...**", parse_mode="Markdown")
            
            # استخراج ID پین
            pin_id = None
            if "/pin/" in url:
                pin_id = url.split("/pin/")[-1].split("/")[0].split("?")[0]
            elif "pin_id=" in url:
                pin_id = url.split("pin_id=")[-1].split("&")[0]
            
            if pin_id:
                # API‌های مختلف
                apis = [
                    f"https://www.pinterest.com/resource/PinResource/get/?source_url=/pin/{pin_id}/",
                    f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}",
                    f"https://ar.savepin.io/pin/{pin_id}",
                    f"https://pinterest-scraper.vercel.app/api/pin?id={pin_id}",
                ]
                
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                }
                
                for api_url in apis:
                    try:
                        response = requests.get(api_url, headers=headers, timeout=15)
                        if response.status_code == 200:
                            data = response.json()
                            
                            img_url = None
                            
                            # بررسی ساختارهای مختلف پاسخ
                            if "resource_response" in data and "data" in data["resource_response"]:
                                pin_data = data["resource_response"]["data"]
                                if "images" in pin_data:
                                    images = pin_data["images"]
                                    if "orig" in images:
                                        img_url = images["orig"]["url"]
                                    elif "736x" in images:
                                        img_url = images["736x"]["url"]
                                    elif "600x" in images:
                                        img_url = images["600x"]["url"]
                            elif "data" in data and len(data["data"]) > 0:
                                pin_data = data["data"][0]
                                if "images" in pin_data:
                                    img_url = pin_data["images"].get("orig", {}).get("url")
                            elif "image" in data:
                                img_url = data["image"]
                            
                            if img_url:
                                img_response = requests.get(img_url, headers=headers, timeout=30)
                                if img_response.status_code == 200:
                                    filename = f"{DOWNLOAD_PATH}/pinterest_api_{int(time.time())}.jpg"
                                    with open(filename, "wb") as f:
                                        f.write(img_response.content)
                                    
                                    with open(filename, "rb") as f:
                                        bot.send_photo(chat_id, f, caption=f"✅ **عکس پینترست**")
                                    
                                    db.add_download(user_id, chat_id, url, "photo", len(img_response.content), 
                                                  "group" if is_group else "private", "Pinterest")
                                    os.remove(filename)
                                    return True
                    except:
                        continue
        except Exception as e:
            print(f"خطا در روش API: {e}")
        
        # روش 3: استفاده از yt-dlp با تنظیمات مخصوص
        try:
            bot.send_message(chat_id, "🔄 **روش 3: yt-dlp پیشرفته...**", parse_mode="Markdown")
            
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": f"{DOWNLOAD_PATH}/pinterest_%(title)s.%(ext)s",
                "ignoreerrors": True,
                "format": "best",
                "extract_flat": False,
                "force_generic_extractor": False,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                "extractor_args": {
                    "pinterest": {
                        "embed": True,
                        "download_all": True,
                    }
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    # پیدا کردن فایل
                    files = sorted(os.listdir(DOWNLOAD_PATH), key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_PATH, x)))
                    if files:
                        filename = os.path.join(DOWNLOAD_PATH, files[-1])
                        
                        with open(filename, "rb") as f:
                            if filename.endswith((".jpg", ".jpeg", ".png")):
                                bot.send_photo(chat_id, f, caption=f"✅ **عکس پینترست**")
                            elif filename.endswith((".mp4", ".webm")):
                                bot.send_video(chat_id, f, caption=f"✅ **ویدیو پینترست**")
                            else:
                                bot.send_document(chat_id, f, caption=f"✅ **محتوای پینترست**")
                        
                        size = os.path.getsize(filename)
                        db.add_download(user_id, chat_id, url, "media", size, 
                                      "group" if is_group else "private", "Pinterest")
                        os.remove(filename)
                        return True
        except Exception as e:
            print(f"خطا در روش yt-dlp: {e}")
        
        # روش 4: استفاده از سرویس‌های دانلود آنلاین
        try:
            bot.send_message(chat_id, "🔄 **روش 4: سرویس آنلاین...**", parse_mode="Markdown")
            
            # سرویس‌های مختلف
            services = [
                f"https://savepin.app/download?url={url}&type=redirect",
                f"https://pinterestvideodownloader.com/download?url={url}",
                f"https://www.expertstool.com/pinterest-image-downloader/?url={url}",
            ]
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            
            for service_url in services:
                try:
                    response = requests.get(service_url, headers=headers, timeout=15, allow_redirects=True)
                    if response.status_code == 200:
                        # استخراج لینک دانلود
                        download_links = re.findall(r'https?://[^\s"\']+\.(jpg|jpeg|png|gif|mp4|webm)', response.text)
                        
                        for link in download_links:
                            if link.startswith("http"):
                                file_response = requests.get(link, headers=headers, timeout=30, stream=True)
                                if file_response.status_code == 200:
                                    ext = link.split('.')[-1].split('?')[0]
                                    filename = f"{DOWNLOAD_PATH}/pinterest_service_{int(time.time())}.{ext}"
                                    
                                    with open(filename, "wb") as f:
                                        for chunk in file_response.iter_content(chunk_size=8192):
                                            if chunk:
                                                f.write(chunk)
                                    
                                    with open(filename, "rb") as f:
                                        if ext in ['jpg', 'jpeg', 'png']:
                                            bot.send_photo(chat_id, f, caption=f"✅ **عکس پینترست**")
                                        elif ext == 'gif':
                                            bot.send_document(chat_id, f, caption=f"✅ **GIF پینترست**")
                                        else:
                                            bot.send_video(chat_id, f, caption=f"✅ **ویدیو پینترست**")
                                    
                                    db.add_download(user_id, chat_id, url, "media", os.path.getsize(filename), 
                                                  "group" if is_group else "private", "Pinterest")
                                    os.remove(filename)
                                    return True
                except:
                    continue
        except Exception as e:
            print(f"خطا در روش سرویس آنلاین: {e}")
        
        # روش 5: تلاش با روش عمومی yt-dlp
        try:
            bot.send_message(chat_id, "🔄 **روش 5: تلاش نهایی...**", parse_mode="Markdown")
            
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": f"{DOWNLOAD_PATH}/pinterest_final_%(title)s.%(ext)s",
                "ignoreerrors": True,
                "format": "best",
                "force_generic_extractor": True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    files = sorted(os.listdir(DOWNLOAD_PATH), key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_PATH, x)))
                    if files:
                        filename = os.path.join(DOWNLOAD_PATH, files[-1])
                        
                        with open(filename, "rb") as f:
                            bot.send_document(chat_id, f, caption=f"✅ **محتوای پینترست**")
                        
                        size = os.path.getsize(filename)
                        db.add_download(user_id, chat_id, url, "media", size, 
                                      "group" if is_group else "private", "Pinterest")
                        os.remove(filename)
                        return True
        except:
            pass
        
        # اگر هیچ روشی جواب نداد، لینک جایگزین پیشنهاد بده
        bot.send_message(chat_id, 
            "❌ **پینترست از دانلود مستقیم جلوگیری می‌کند**\n\n"
            "💡 **راه‌حل‌های جایگزین:**\n\n"
            "1️⃣ **روش اول:**\n"
            "• لینک را در مرورگر باز کنید\n"
            "• روی عکس راست کلیک کنید\n"
            "• گزینه 'Save image as...' را انتخاب کنید\n"
            "• فایل ذخیره شده را به ربات بفرستید\n\n"
            "2️⃣ **روش دوم (سایت جایگزین):**\n"
            "• به سایت https://savepin.app بروید\n"
            "• لینک پینترست را جایگذاری کنید\n"
            "• دکمه Download را بزنید\n"
            "• فایل دانلود شده را به ربات بفرستید\n\n"
            "3️⃣ **روش سوم (ربات دیگر):**\n"
            "• از ربات @SavePinBot استفاده کنید\n"
            "• لینک را برای اون بفرستید\n"
            "• فایل را از اون بگیرید و به من بفرستید",
            parse_mode="Markdown")
        
        return False
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

# ================= تابع دانلود تیک‌تاک =================
def download_tiktok(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "🎵 **در حال دریافت از تیک‌تاک...**", parse_mode="Markdown")
        
        # روش 1: استفاده از API
        try:
            apis = [
                {
                    "url": "https://api.cobalt.tools/api/json",
                    "headers": {
                        "User-Agent": "Mozilla/5.0",
                        "Content-Type": "application/json",
                    }
                },
                {
                    "url": "https://tikwm.com/api/",
                    "headers": {
                        "User-Agent": "Mozilla/5.0",
                        "Content-Type": "application/x-www-form-urlencoded"
                    }
                }
            ]
            
            for api in apis:
                try:
                    if "cobalt" in api["url"]:
                        data = {"url": url, "downloadMode": "auto"}
                        response = requests.post(api["url"], json=data, headers=api["headers"], timeout=30)
                    elif "tikwm" in api["url"]:
                        data = {"url": url, "hd": 1}
                        response = requests.post(api["url"], data=data, headers=api["headers"], timeout=30)
                    
                    if response.status_code == 200:
                        result = response.json()
                        download_url = None
                        
                        if "cobalt" in api["url"] and result.get("status") == "success":
                            download_url = result.get("url")
                        elif "tikwm" in api["url"] and result.get("data"):
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
                    continue
        except:
            pass
        
        # روش 2: yt-dlp
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": f"{DOWNLOAD_PATH}/tiktok_%(title)s.%(ext)s",
                "ignoreerrors": True,
                "format": "best",
                "extractor_args": {"tiktok": {"app_version": "latest"}}
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    filename = None
                    for f in os.listdir(DOWNLOAD_PATH):
                        if info.get("title", "") in f:
                            filename = os.path.join(DOWNLOAD_PATH, f)
                            break
                    
                    if filename and os.path.exists(filename):
                        size = os.path.getsize(filename)
                        with open(filename, "rb") as f:
                            bot.send_video(chat_id, f, caption=f"✅ **{info.get('title', 'تیک‌تاک')}**")
                        
                        db.add_download(user_id, chat_id, url, "video", size, 
                                      "group" if is_group else "private", "TikTok")
                        os.remove(filename)
                        return True
        except:
            pass
        
        return False
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

# ================= تابع دانلود اینستاگرام =================
def download_instagram(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "📸 **در حال دریافت از اینستاگرام...**", parse_mode="Markdown")
        
        # روش 1: API cobalt.tools
        try:
            api_url = "https://api.cobalt.tools/api/json"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
            }
            data = {"url": url, "downloadMode": "auto"}
            
            response = requests.post(api_url, json=data, headers=headers, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    download_url = result["url"]
                    
                    file_response = requests.get(download_url, timeout=60)
                    if file_response.status_code == 200:
                        filename = f"{DOWNLOAD_PATH}/instagram_{int(time.time())}.mp4"
                        with open(filename, "wb") as f:
                            f.write(file_response.content)
                        
                        with open(filename, "rb") as f:
                            bot.send_video(chat_id, f, caption=f"✅ **دانلود از اینستاگرام**")
                        
                        db.add_download(user_id, chat_id, url, "video", len(file_response.content), 
                                      "group" if is_group else "private", "Instagram")
                        os.remove(filename)
                        return True
        except:
            pass
        
        # روش 2: yt-dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": f"{DOWNLOAD_PATH}/instagram_%(title)s.%(ext)s",
            "ignoreerrors": True,
            "format": "best",
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if info:
                filename = None
                for f in os.listdir(DOWNLOAD_PATH):
                    if info.get("title", "") in f:
                        filename = os.path.join(DOWNLOAD_PATH, f)
                        break
                
                if filename and os.path.exists(filename):
                    size = os.path.getsize(filename)
                    with open(filename, "rb") as f:
                        bot.send_video(chat_id, f, caption=f"✅ **{info.get('title', 'اینستاگرام')}**")
                    
                    db.add_download(user_id, chat_id, url, "video", size, 
                                  "group" if is_group else "private", "Instagram")
                    os.remove(filename)
                    return True
        
        return False
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

# ================= تابع دانلود عمومی برای بقیه سایت‌ها =================
def download_general(url, chat_id, user_id, is_group=False):
    try:
        bot.send_message(chat_id, "🌐 **در حال دریافت از سایت...**", parse_mode="Markdown")
        
        # لیست User-Agent های مختلف
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        ]
        
        # تنظیمات yt-dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": f"{DOWNLOAD_PATH}/%(title)s.%(ext)s",
            "ignoreerrors": True,
            "format": "best[filesize<300M]/best",
            "socket_timeout": 30,
            "retries": 3,
            "http_headers": {
                "User-Agent": random.choice(user_agents),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            }
        }
        
        msg = bot.send_message(chat_id, "⏳ **در حال دریافت اطلاعات...**", parse_mode="Markdown")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if info:
                title = clean_filename(info.get("title", "file"))
                
                # پیدا کردن فایل
                filename = None
                for f in os.listdir(DOWNLOAD_PATH):
                    if title in f:
                        filename = os.path.join(DOWNLOAD_PATH, f)
                        break
                
                if not filename:
                    files = sorted(os.listdir(DOWNLOAD_PATH), key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_PATH, x)))
                    if files:
                        filename = os.path.join(DOWNLOAD_PATH, files[-1])
                
                if filename and os.path.exists(filename):
                    size = os.path.getsize(filename)
                    
                    if size <= MAX_FILE_SIZE:
                        bot.edit_message_text("📤 **در حال آپلود...**", chat_id, msg.message_id, parse_mode="Markdown")
                        
                        with open(filename, "rb") as f:
                            if filename.endswith((".mp4", ".mkv", ".webm")):
                                bot.send_video(chat_id, f, caption=f"✅ **{title}**")
                            elif filename.endswith((".mp3", ".m4a")):
                                bot.send_audio(chat_id, f, caption=f"✅ **{title}**")
                            elif filename.endswith((".jpg", ".jpeg", ".png", ".gif")):
                                bot.send_photo(chat_id, f, caption=f"✅ **{title}**")
                            else:
                                bot.send_document(chat_id, f, caption=f"✅ **{title}**")
                        
                        db.add_download(user_id, chat_id, url, "general", size, 
                                      "group" if is_group else "private", "Other")
                        os.remove(filename)
                        bot.delete_message(chat_id, msg.message_id)
                        return True
        
        return False
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ **خطا:**\n`{str(e)[:200]}`", parse_mode="Markdown")
        return False

# ================= تابع دانلود اصلی =================
def download_media(url, chat_id, user_id, is_group=False):
    try:
        platform = detect_platform(url)
        
        # انتخاب تابع مناسب بر اساس پلتفرم
        if platform == "Pinterest":
            return download_pinterest(url, chat_id, user_id, is_group)
        elif platform == "Tiktok":
            return download_tiktok(url, chat_id, user_id, is_group)
        elif platform == "Instagram":
            return download_instagram(url, chat_id, user_id, is_group)
        else:
            return download_general(url, chat_id, user_id, is_group)
        
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
        f"🎬 سلام {message.from_user.first_name or message.from_user.username}!\n\n"
        "من ربات **𝗧𝗢𝗣 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗘𝗥** هستم 🤖\n"
        "می‌تونم از **همه سایت‌ها** برات دانلود کنم!\n\n"
        "✅ **سایت‌های پشتیبانی شده:**\n"
        "• یوتیوب | تیک‌تاک | اینستاگرام\n"
        "• توییتر | فیسبوک | پینترست\n"
        "• آپارات | تلوبیون | فیلیمو\n"
        "• تماشا | نماشا | کلیپس\n"
        "• و هزاران سایت دیگه!\n\n"
        "✅ **حجم مجاز:** ۳۰۰ مگابایت\n"
        "✅ **فرمت‌ها:** ویدیو، صدا، عکس، GIF\n\n"
        "📌 **فقط کافیه لینک رو بفرستی!**"
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
    
    bot.reply_to(message, "✅ **لینک دریافت شد، شروع دانلود...**", parse_mode="Markdown")
    threading.Thread(
        target=download_media,
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
    print("="*50)
    print("🚀 راه‌اندازی ربات قدرتمند دانلود...")
    print("="*50)
    print(f"👤 آیدی ادمین: {ADMIN_ID}")
    print(f"📁 مسیر دانلود: {DOWNLOAD_PATH}")
    print(f"📊 حجم مجاز: {MAX_FILE_SIZE/1024/1024}MB")
    print("="*50)
    
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
    print("✅ پشتیبانی از تمام سایت‌ها فعال شد")
    print("="*50)
    
    app.run(host="0.0.0.0", port=PORT)
