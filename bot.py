# -*- coding: utf-8 -*-
import os
import threading
import time
import re
import requests
import json
import subprocess
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from flask import Flask, request
import instaloader
import yt_dlp
import random

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

# ================= دیتابیس =================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()

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
        CREATE TABLE IF NOT EXISTS downloads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            size INTEGER,
            timestamp TIMESTAMP,
            method TEXT
        )
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id,is_admin) VALUES(?,1)", (ADMIN_ID,))
        self.conn.commit()

    def add_user(self, user_id, username, first_name):
        now = datetime.now()
        self.cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE users SET last_use=? WHERE user_id=?", (now, user_id))
        else:
            self.cursor.execute("INSERT INTO users(user_id,username,first_name,joined_date,last_use) VALUES(?,?,?,?,?)",
                              (user_id, username, first_name, now, now))
        self.conn.commit()

    def add_download(self, user_id, url, size, method):
        now = datetime.now()
        self.cursor.execute("INSERT INTO downloads(user_id,url,size,timestamp,method) VALUES(?,?,?,?,?)",
                          (user_id, url, size, now, method))
        self.cursor.execute("UPDATE users SET download_count=download_count+1 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def check_membership(self, user_id):
        try:
            for username, _ in REQUIRED_CHANNELS:
                member = bot.get_chat_member(username, user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    return False
            return True
        except:
            return False

    def is_blocked(self, user_id):
        self.cursor.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,))
        r = self.cursor.fetchone()
        return r and r[0] == 1

    def get_setting(self, key):
        self.cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = self.cursor.fetchone()
        return r[0] if r else "ON"

# ================= موتور دانلود اینستاگرام (۱۰ روش) =================
class InstagramDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        self.instaloader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=3
        )

    def setup_session(self):
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        })

    def extract_shortcode(self, url):
        patterns = [
            r'instagram\.com/p/([^/?]+)',
            r'instagram\.com/reel/([^/?]+)',
            r'instagram\.com/tv/([^/?]+)',
            r'instagram\.com/stories/(?:[^/]+/)?([^/?]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    # ========== روش ۱: RapidAPI ==========
    def method_rapidapi(self, url):
        try:
            rapid_api_key = "32c3cfa93amsh1e9be3ab9c2b24ap1ca06djsn7bcb853f466f"  # اینو عوض کن با کلید خودت
            
            response = requests.get(
                "https://instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com/get-info-rapidapi",
                headers={
                    "X-RapidAPI-Key": rapid_api_key,
                    "X-RapidAPI-Host": "instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com"
                },
                params={"url": url}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("media") and data["media"][0].get("video_url"):
                    return self.download_file(data["media"][0]["video_url"], "rapidapi")
        except:
            return None

    # ========== روش ۲: SaveInsta API ==========
    def method_saveinsta(self, url):
        try:
            response = requests.post(
                "https://saveinsta.app/api/ajaxSearch",
                data={"q": url, "t": "media"},
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    # استخراج لینک دانلود
                    video_urls = re.findall(r'href="([^"]+\.mp4)"', data["data"])
                    image_urls = re.findall(r'href="([^"]+\.(jpg|png))"', data["data"])
                    
                    for url_match in video_urls:
                        return self.download_file(url_match, "saveinsta")
                    for url_match in image_urls:
                        return self.download_file(url_match[0], "saveinsta")
        except:
            return None

    # ========== روش ۳: SnapInsta ==========
    def method_snapinsta(self, url):
        try:
            response = requests.post(
                "https://snapinsta.app/api/ajaxSearch",
                data={"q": url, "t": "media"},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    video_urls = re.findall(r'href="([^"]+\.mp4)"', data["data"])
                    image_urls = re.findall(r'href="([^"]+\.(jpg|png))"', data["data"])
                    
                    for url_match in video_urls:
                        return self.download_file(url_match, "snapinsta")
                    for url_match in image_urls:
                        return self.download_file(url_match[0], "snapinsta")
        except:
            return None

    # ========== روش ۴: IGDownloader ==========
    def method_igdownloader(self, url):
        try:
            response = requests.post(
                "https://igdownloader.app/api/ajaxSearch",
                data={"q": url, "t": "media"},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    video_urls = re.findall(r'href="([^"]+\.mp4)"', data["data"])
                    image_urls = re.findall(r'href="([^"]+\.(jpg|png))"', data["data"])
                    
                    for url_match in video_urls:
                        return self.download_file(url_match, "igdownloader")
                    for url_match in image_urls:
                        return self.download_file(url_match[0], "igdownloader")
        except:
            return None

    # ========== روش ۵: Cobalt Tools ==========
    def method_cobalt(self, url):
        try:
            response = requests.post(
                "https://api.cobalt.tools/api/json",
                json={"url": url, "downloadMode": "auto", "videoQuality": "max"},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success" and data.get("url"):
                    return self.download_file(data["url"], "cobalt")
        except:
            return None

    # ========== روش ۶: yt-dlp ==========
    def method_ytdlp(self, url):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
                'outtmpl': f'{DOWNLOAD_PATH}/instagram_%(title)s.%(ext)s',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    # پیدا کردن فایل
                    files = os.listdir(DOWNLOAD_PATH)
                    for f in sorted(files, key=lambda x: os.path.getctime(os.path.join(DOWNLOAD_PATH, x)), reverse=True):
                        if f.endswith(('.mp4', '.jpg', '.png', '.webp')):
                            filepath = os.path.join(DOWNLOAD_PATH, f)
                            return {
                                'filename': filepath,
                                'size': os.path.getsize(filepath),
                                'method': 'ytdlp'
                            }
        except:
            return None

    # ========== روش ۷: Instaloader ==========
    def method_instaloader(self, url):
        try:
            shortcode = self.extract_shortcode(url)
            if not shortcode:
                return None
            
            post = instaloader.Post.from_shortcode(self.instaloader.context, shortcode)
            
            if post.is_video:
                # دانلود ویدیو
                video_url = post.video_url
                return self.download_file(video_url, "instaloader")
            else:
                # دانلود عکس
                image_url = post.url
                return self.download_file(image_url, "instaloader")
        except:
            return None

    # ========== روش ۸: Instagram Video Downloader API ==========
    def method_instagram_video_api(self, url):
        try:
            response = requests.get(
                "https://instagram-video-downloader-download-instagram-videos.p.rapidapi.com/instagram",
                headers={
                    "X-RapidAPI-Key": "32c3cfa93amsh1e9be3ab9c2b24ap1ca06djsn7bcb853f466f",
                    "X-RapidAPI-Host": "instagram-video-downloader-download-instagram-videos.p.rapidapi.com"
                },
                params={"url": url},
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("video") and data["video"][0].get("video"):
                    return self.download_file(data["video"][0]["video"], "instagram_video_api")
        except:
            return None

    # ========== روش ۹: استخراج مستقیم از HTML ==========
    def method_direct_extract(self, url):
        try:
            # استفاده از یوزر ایجنت موبایل
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            }
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                # الگوهای مختلف برای پیدا کردن ویدیو و عکس
                patterns = [
                    r'"video_url":"([^"]+)"',
                    r'"display_url":"([^"]+)"',
                    r'<meta property="og:video" content="([^"]+)"',
                    r'<meta property="og:image" content="([^"]+)"',
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
                            if '.mp4' in media_url or '.jpg' in media_url or '.png' in media_url:
                                return self.download_file(media_url, "direct_extract")
        except:
            return None

    # ========== روش ۱۰: دانلود با لینک مستقیم از سرور ==========
    def method_direct_download(self, url):
        try:
            # استفاده از سرویس‌های مختلف
            services = [
                {"url": "https://instasave.website/api/ajaxSearch", "data": {"q": url, "t": "media"}},
                {"url": "https://insta.saveinsta.app/api/ajaxSearch", "data": {"q": url, "t": "media"}},
            ]
            
            for service in services:
                try:
                    response = requests.post(service["url"], data=service["data"], timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("data"):
                            urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                            for url_match in urls:
                                download_url = url_match[0]
                                if download_url:
                                    return self.download_file(download_url, "direct_download")
                except:
                    continue
        except:
            return None

    def download_file(self, url, method_name):
        """دانلود فایل از لینک مستقیم"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.instagram.com/",
            }
            
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            
            if response.status_code == 200:
                # تشخیص نوع فایل
                content_type = response.headers.get('content-type', '')
                if 'video' in content_type:
                    ext = '.mp4'
                elif 'image' in content_type:
                    ext = '.jpg'
                else:
                    ext = '.mp4'
                
                filename = f"{DOWNLOAD_PATH}/instagram_{method_name}_{int(time.time())}{ext}"
                
                # دانلود با نمایش پیشرفت
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = os.path.getsize(filename)
                if file_size < 1024:  # فایل خیلی کوچیکه
                    os.remove(filename)
                    return None
                
                return {
                    'filename': filename,
                    'size': file_size,
                    'method': method_name
                }
        except Exception as e:
            print(f"خطا در دانلود فایل با روش {method_name}: {e}")
            return None

    def download(self, url, chat_id, user_id, msg_id=None):
        """تابع اصلی دانلود با ۱۰ روش مختلف"""
        
        methods = [
            ("🟢 RapidAPI", self.method_rapidapi),
            ("🟢 SaveInsta", self.method_saveinsta),
            ("🟢 SnapInsta", self.method_snapinsta),
            ("🟢 IGDownloader", self.method_igdownloader),
            ("🟢 Cobalt", self.method_cobalt),
            ("🟢 yt-dlp", self.method_ytdlp),
            ("🟢 Instaloader", self.method_instaloader),
            ("🟢 Instagram Video API", self.method_instagram_video_api),
            ("🟢 Direct Extract", self.method_direct_extract),
            ("🟢 Direct Download", self.method_direct_download),
        ]
        
        # شافل کردن روش‌ها برای شانس بیشتر
        random.shuffle(methods)
        
        if msg_id:
            try:
                bot.edit_message_text(
                    f"📥 **شروع دانلود از اینستاگرام**\n"
                    f"🔍 {len(methods)} روش مختلف آماده شد...",
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
                            f"🔄 **روش {i}/{len(methods)}**\n"
                            f"📡 در حال امتحان: {method_name}",
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
                                f"📤 **در حال آپلود...**\n"
                                f"📊 حجم: {result['size']/1024/1024:.1f} MB\n"
                                f"✅ روش موفق: {method_name}",
                                chat_id,
                                msg_id,
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                    
                    # ارسال فایل
                    with open(result['filename'], 'rb') as f:
                        if result['filename'].endswith('.mp4'):
                            bot.send_video(
                                chat_id, 
                                f, 
                                caption=f"✅ **دانلود با موفقیت انجام شد!**\n"
                                       f"📥 روش: {method_name}\n"
                                       f"📊 حجم: {result['size']/1024/1024:.1f} MB\n"
                                       f"📌 @top_topy_downloader",
                                timeout=120
                            )
                        else:
                            bot.send_document(
                                chat_id, 
                                f, 
                                caption=f"✅ **دانلود با موفقیت انجام شد!**\n"
                                       f"📥 روش: {method_name}\n"
                                       f"📊 حجم: {result['size']/1024/1024:.1f} MB\n"
                                       f"📌 @top_topy_downloader",
                                timeout=120
                            )
                    
                    # ثبت در دیتابیس
                    db.add_download(user_id, url, result['size'], result['method'])
                    
                    # پاک کردن فایل
                    os.remove(result['filename'])
                    
                    if msg_id:
                        try:
                            bot.edit_message_text(
                                f"✅ **دانلود کامل شد!**\n"
                                f"🔧 روش: {method_name}\n"
                                f"📊 حجم: {result['size']/1024/1024:.1f} MB",
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
                    f"❌ **متأسفانه دانلود با مشکل مواجه شد**\n\n"
                    f"💡 **تمامی {len(methods)} روش امتحان شدند**\n"
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

# ================= ایجاد نمونه =================
db = Database()
instagram_downloader = InstagramDownloader()
bot = telebot.TeleBot(TOKEN)

# ================= توابع کمکی =================
def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

def is_instagram_url(url):
    domains = ['instagram.com', 'instagr.am']
    return any(domain in url.lower() for domain in domains)

# ================= هندلرهای ربات =================
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
        f"📸 **سلام {message.from_user.first_name or message.from_user.username}!**\n\n"
        "به **بهترین ربات دانلود اینستاگرام** خوش اومدی 🤖\n\n"
        "✅ **قابلیت‌های من:**\n"
        "• دانلود ویدیو و عکس از پست‌ها\n"
        "• دانلود ریلز (Reels)\n"
        "• دانلود IGTV\n"
        "• پشتیبانی از استوری\n\n"
        "⚡ **۱۰ روش مختلف دانلود**\n"
        "🎯 **۱۰۰٪ تضمینی**\n"
        "📦 **حجم مجاز: ۳۰۰ مگابایت**\n\n"
        "📌 **فقط کافیه لینک اینستاگرام رو بفرستی!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if db.check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ عضو نشده‌اید!", show_alert=True)

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    if not message.text.startswith(('http://', 'https://')):
        return

    if db.is_blocked(message.from_user.id):
        bot.reply_to(message, "⛔ شما بلاک هستید")
        return

    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if not db.check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **لطفاً ابتدا در کانال‌ها عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    # استخراج لینک
    urls = re.findall(r'https?://[^\s]+', message.text)
    if not urls:
        return
    
    url = urls[0]
    
    # بررسی اینستاگرام بودن لینک
    if not is_instagram_url(url):
        bot.reply_to(
            message,
            "❌ **لطفاً فقط لینک اینستاگرام ارسال کنید**\n"
            "مثال: https://www.instagram.com/p/...",
            parse_mode="Markdown"
        )
        return
    
    # شروع دانلود
    msg = bot.reply_to(
        message,
        "✅ **لینک دریافت شد**\n"
        "🔄 در حال آماده‌سازی ۱۰ روش دانلود...",
        parse_mode="Markdown"
    )
    
    threading.Thread(
        target=instagram_downloader.download,
        args=(url, message.chat.id, message.from_user.id, msg.message_id),
        daemon=True
    ).start()

# ================= پنل ادمین ساده =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    stats = db.cursor.execute("SELECT COUNT(*), SUM(download_count) FROM users").fetchone()
    total_users = stats[0] or 0
    total_downloads = stats[1] or 0
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"👥 کاربران: {total_users}\n"
    text += f"📥 دانلودها: {total_downloads}\n"
    text += f"🟢 وضعیت: فعال"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

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
    return "ربات دانلود اینستاگرام با ۱۰ روش - ۱۰۰٪ تضمینی"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*60)
    print("📸 ربات دانلود اینستاگرام با ۱۰ روش")
    print("="*60)
    print("✅ روش‌های دانلود:")
    print("   1. RapidAPI")
    print("   2. SaveInsta")
    print("   3. SnapInsta")
    print("   4. IGDownloader")
    print("   5. Cobalt Tools")
    print("   6. yt-dlp")
    print("   7. Instaloader")
    print("   8. Instagram Video API")
    print("   9. Direct Extract")
    print("   10. Direct Download")
    print("="*60)
    print("🎯 ۱۰۰٪ تضمینی")
    print("="*60)
    
    # پاکسازی فایل‌های قدیمی
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except:
            pass
    
    # تنظیم وب‌هوک
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات فعال شد!")
    
    app.run(host="0.0.0.0", port=PORT)
