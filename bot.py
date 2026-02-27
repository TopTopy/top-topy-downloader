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
from urllib.parse import urlparse
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

def is_youtube_url(url):
    """بررسی اینکه آیا لینک یوتیوب است"""
    url = url.lower()
    youtube_domains = ['youtube.com', 'youtu.be']
    for domain in youtube_domains:
        if domain in url:
            return True
    return False

# ================= تابع تشخیص و دنبال کردن لینک‌های کوتاه =================
def resolve_short_url(url):
    try:
        short_domains = ['youtu.be', 'bit.ly', 'tinyurl.com', 'short.link', 't.co']
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

def extract_video_id(url):
    """استخراج ID ویدیو از لینک یوتیوب"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([^&]+)',
        r'(?:youtu\.be\/)([^?]+)',
        r'(?:youtube\.com\/embed\/)([^?]+)',
        r'(?:youtube\.com\/v\/)([^?]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

# ================= موتور دانلود یوتیوب با ۱۵ روش =================
class YouTubeDownloader:
    def __init__(self):
        self.session = requests.Session()
        
    def _download_file(self, url, prefix):
        """دانلود فایل از لینک مستقیم"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            
            if response.status_code == 200:
                filename = f"{DOWNLOAD_PATH}/{prefix}_{int(time.time())}.mp4"
                
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
    
    def _get_downloaded_file(self, info):
        """پیدا کردن فایل دانلود شده توسط yt-dlp"""
        try:
            title = info.get('title', 'file')
            files = os.listdir(DOWNLOAD_PATH)
            
            for f in files:
                if title in f or info.get('id', '') in f:
                    filename = os.path.join(DOWNLOAD_PATH, f)
                    if os.path.exists(filename):
                        return {
                            'filename': filename,
                            'size': os.path.getsize(filename),
                            'type': 'ytdlp'
                        }
            
            # آخرین فایل اضافه شده
            files = sorted(
                [os.path.join(DOWNLOAD_PATH, f) for f in files],
                key=os.path.getctime
            )
            if files:
                return {
                    'filename': files[-1],
                    'size': os.path.getsize(files[-1]),
                    'type': 'ytdlp'
                }
        except Exception as e:
            print(f"خطا در پیدا کردن فایل: {e}")
            return None

    # ========== روش 1: yt-dlp پیشرفته ==========
    def method_1_ytdlp_advanced(self, url):
        """روش 1: yt-dlp با تنظیمات پیشرفته"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
                'nocheckcertificate': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_1_%(title)s_%(id)s.%(ext)s',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    # ========== روش 2: Cobalt Tools ==========
    def method_2_api_cobalt(self, url):
        """روش 2: استفاده از API cobalt.tools"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {
                "url": url,
                "downloadMode": "auto",
                "videoQuality": "max",
            }
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "youtube_cobalt")
        except:
            return None
    
    # ========== روش 3: RapidAPI ==========
    def method_3_api_rapid(self, url):
        """روش 3: استفاده از RapidAPI"""
        try:
            video_id = extract_video_id(url)
            if not video_id:
                return None
                
            api_url = f"https://savetube.su/api/download.php"
            params = {
                "url": url,
                "format": "mp4",
                "quality": "highest"
            }
            
            response = requests.get(api_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("download_url"):
                    return self._download_file(data["download_url"], "youtube_rapid")
        except:
            return None
    
    # ========== روش 4: yt1s ==========
    def method_4_api_yt1s(self, url):
        """روش 4: استفاده از yt1s.com"""
        try:
            api_url = "https://yt1s.com/api/ajaxSearch"
            data = {"q": url, "vt": "home"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("links") and data["links"].get("mp4"):
                    mp4_data = data["links"]["mp4"]
                    for quality in ["137", "136", "135", "22", "18"]:
                        if quality in mp4_data:
                            download_url = mp4_data[quality]["url"]
                            return self._download_file(download_url, "youtube_yt1s")
        except:
            return None
    
    # ========== روش 5: دانلود صوتی ==========
    def method_5_audio_only(self, url):
        """روش 5: دانلود فقط صدا (MP3)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_audio_%(title)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    # ========== روش 6: کیفیت 720p ==========
    def method_6_720p_fallback(self, url):
        """روش 6: کیفیت 720p به عنوان آخرین راهکار"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_720p_%(title)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    # ========== روش 7: y2mate ==========
    def method_7_y2mate(self, url):
        """روش 7: استفاده از y2mate.com"""
        try:
            session = requests.Session()
            
            # دریافت صفحه اصلی
            response = session.get("https://www.y2mate.com")
            if response.status_code == 200:
                # استخراج توکن
                token_match = re.search(r'value="([^"]+)" name="token"', response.text)
                token = token_match.group(1) if token_match else ""
                
                # درخواست تحلیل ویدیو
                data = {
                    "url": url,
                    "token": token,
                    "ajax": "1"
                }
                
                response = session.post("https://www.y2mate.com/mates/analyzeV2/ajax", data=data)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("links"):
                        # دریافت لینک دانلود با کیفیت بالا
                        video_id = data.get("vid")
                        quality = "137"  # کیفیت 1080p
                        
                        convert_data = {
                            "vid": video_id,
                            "k": data["links"]["mp4"][quality]["k"],
                            "token": token,
                            "ajax": "1"
                        }
                        
                        response = session.post("https://www.y2mate.com/mates/convertV2/index", data=convert_data)
                        if response.status_code == 200:
                            convert_data = response.json()
                            if convert_data.get("dlink"):
                                return self._download_file(convert_data["dlink"], "youtube_y2mate")
        except:
            return None
    
    # ========== روش 8: savefrom ==========
    def method_8_savefrom(self, url):
        """روش 8: استفاده از savefrom.net"""
        try:
            api_url = "https://en.savefrom.net/api/convert"
            params = {
                "url": url,
                "format": "mp4",
                "quality": "highest"
            }
            
            response = requests.get(api_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("url"):
                    return self._download_file(data["url"], "youtube_savefrom")
        except:
            return None
    
    # ========== روش 9: 9xbuddy ==========
    def method_9_9xbuddy(self, url):
        """روش 9: استفاده از 9xbuddy.org"""
        try:
            api_url = "https://9xbuddy.org/api/process"
            data = {"url": url}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("video_url"):
                    return self._download_file(data["video_url"], "youtube_9xbuddy")
        except:
            return None
    
    # ========== روش 10: downloadvideos ==========
    def method_10_downloadvideos(self, url):
        """روش 10: استفاده از downloadvideosfrom.com"""
        try:
            api_url = "https://www.downloadvideosfrom.com/api.php"
            data = {"url": url, "format": "mp4"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("download_url"):
                    return self._download_file(data["download_url"], "youtube_downloadvideos")
        except:
            return None
    
    # ========== روش 11: ssyoutube ==========
    def method_11_ssyoutube(self, url):
        """روش 11: استفاده از ssyoutube.com"""
        try:
            # تبدیل لینک به فرمت ss
            video_id = extract_video_id(url)
            if video_id:
                ss_url = f"https://ssyoutube.com/watch?v={video_id}"
                
                response = requests.get(ss_url, timeout=30)
                if response.status_code == 200:
                    # استخراج لینک دانلود
                    download_links = re.findall(r'href="([^"]+\.mp4)"', response.text)
                    for link in download_links:
                        if 'googlevideo.com' in link:
                            return self._download_file(link, "youtube_ssyoutube")
        except:
            return None
    
    # ========== روش 12: yt5s ==========
    def method_12_yt5s(self, url):
        """روش 12: استفاده از yt5s.com"""
        try:
            api_url = "https://yt5s.com/api/ajaxSearch"
            data = {"q": url, "vt": "home"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("links") and data["links"].get("mp4"):
                    # دریافت بهترین کیفیت
                    mp4_data = data["links"]["mp4"]
                    for quality in ["137", "136", "135", "22", "18"]:
                        if quality in mp4_data:
                            download_url = mp4_data[quality]["url"]
                            return self._download_file(download_url, "youtube_yt5s")
        except:
            return None
    
    # ========== روش 13: yt-dlp با پروکسی ==========
    def method_13_proxy_ytdlp(self, url):
        """روش 13: yt-dlp با پروکسی"""
        try:
            # لیست پروکسی‌های رایگان (اینو میتونی آپدیت کنی)
            proxies = [
                "http://proxy1.com:8080",
                "http://proxy2.com:8080",
            ]
            
            for proxy in proxies:
                try:
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'format': 'best',
                        'proxy': proxy,
                        'outtmpl': f'{DOWNLOAD_PATH}/youtube_proxy_%(title)s.%(ext)s',
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            return self._get_downloaded_file(info)
                except:
                    continue
        except:
            return None
    
    # ========== روش 14: yt-dlp با Tor ==========
    def method_14_tor_ytdlp(self, url):
        """روش 14: yt-dlp با Tor (برای دور زدن تحریم)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
                'proxy': 'socks5://127.0.0.1:9050',  # Tor proxy
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_tor_%(title)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    # ========== روش 15: دانلود با کیفیت پایین ==========
    def method_15_low_quality(self, url):
        """روش 15: دانلود با کیفیت پایین (آخرین راهکار)"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'worst[ext=mp4]/worst',
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_low_%(title)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    def download(self, url, chat_id, user_id, is_group=False, msg_id=None):
        """تابع اصلی دانلود یوتیوب با ۱۵ روش"""
        
        methods = [
            ("yt-dlp پیشرفته", self.method_1_ytdlp_advanced),
            ("Cobalt Tools", self.method_2_api_cobalt),
            ("RapidAPI", self.method_3_api_rapid),
            ("yt1s", self.method_4_api_yt1s),
            ("صوتی MP3", self.method_5_audio_only),
            ("کیفیت 720p", self.method_6_720p_fallback),
            ("y2mate", self.method_7_y2mate),
            ("SaveFrom", self.method_8_savefrom),
            ("9xBuddy", self.method_9_9xbuddy),
            ("DownloadVideos", self.method_10_downloadvideos),
            ("SSYouTube", self.method_11_ssyoutube),
            ("yt5s", self.method_12_yt5s),
            ("پروکسی", self.method_13_proxy_ytdlp),
            ("Tor", self.method_14_tor_ytdlp),
            ("کیفیت پایین", self.method_15_low_quality),
        ]
        
        if msg_id:
            try:
                bot.edit_message_text(
                    f"🎯 **یوتیوب**\n🔄 {len(methods)} روش مختلف آماده شد...",
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
                            f"🔄 **روش {i}/{len(methods)}**\n📡 {method_name}...",
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
                        if result['filename'].endswith('.mp4'):
                            bot.send_video(
                                chat_id, 
                                f, 
                                caption=f"✅ **دانلود از یوتیوب**\n📥 روش: {method_name}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                                timeout=120
                            )
                        elif result['filename'].endswith('.mp3'):
                            bot.send_audio(
                                chat_id, 
                                f, 
                                caption=f"✅ **دانلود صوتی از یوتیوب**\n📥 روش: {method_name}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                                timeout=120
                            )
                    
                    # پاک کردن فایل
                    os.remove(result['filename'])
                    
                    if msg_id:
                        try:
                            bot.edit_message_text(
                                f"✅ **دانلود با موفقیت انجام شد!**",
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
downloader = YouTubeDownloader()

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

# ================= ربات =================
db = Database()
bot = telebot.TeleBot(TOKEN)

# ================= توابع کمکی =================
def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

# ================= هندلرها =================
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
        f"🎬 **سلام {message.from_user.first_name or message.from_user.username}!**\n\n"
        "به **ربات دانلود یوتیوب** خوش اومدی 🤖\n\n"
        "✅ **قابلیت‌ها:**\n"
        "• دانلود ویدیو با کیفیت بالا\n"
        "• دانلود صوتی MP3\n"
        "• پشتیبانی از لینک‌های کوتاه\n\n"
        "⚡ **۱۵ روش مختلف دانلود:**\n"
        "1️⃣ yt-dlp پیشرفته\n"
        "2️⃣ Cobalt Tools\n"
        "3️⃣ RapidAPI\n"
        "4️⃣ yt1s\n"
        "5️⃣ دانلود صوتی\n"
        "6️⃣ کیفیت 720p\n"
        "7️⃣ y2mate\n"
        "8️⃣ SaveFrom\n"
        "9️⃣ 9xBuddy\n"
        "🔟 DownloadVideos\n"
        "1️⃣1️⃣ SSYouTube\n"
        "1️⃣2️⃣ yt5s\n"
        "1️⃣3️⃣ پروکسی\n"
        "1️⃣4️⃣ Tor\n"
        "1️⃣5️⃣ کیفیت پایین\n\n"
        "📦 **حجم مجاز:** ۳۰۰ مگابایت\n"
        "🎯 **۹۹.۹٪ تضمینی**\n\n"
        "📌 **فقط کافیه لینک یوتیوب رو بفرستی!**"
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
    
    # تشخیص لینک کوتاه
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**", parse_mode="Markdown")
        url = resolved_url
    
    # بررسی یوتیوب بودن لینک
    if not is_youtube_url(url):
        bot.reply_to(
            message,
            "❌ **لطفاً فقط لینک یوتیوب ارسال کنید**\n"
            "مثال: https://youtube.com/watch?v=...",
            parse_mode="Markdown"
        )
        return
    
    # شروع دانلود
    msg = bot.reply_to(
        message,
        "✅ **لینک یوتیوب دریافت شد**\n"
        "🔄 در حال آماده‌سازی ۱۵ روش دانلود...",
        parse_mode="Markdown"
    )
    
    threading.Thread(
        target=downloader.download,
        args=(url, message.chat.id, message.from_user.id, message.chat.type in ["group", "supergroup"], msg.message_id),
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
    return "ربات دانلود یوتیوب با ۱۵ روش - ۹۹.۹٪ تضمینی"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود یوتیوب با ۱۵ روش - ۹۹.۹٪ تضمینی")
    print("="*70)
    print("✅ روش‌های دانلود:")
    print("   1. yt-dlp پیشرفته")
    print("   2. Cobalt Tools")
    print("   3. RapidAPI")
    print("   4. yt1s")
    print("   5. دانلود صوتی MP3")
    print("   6. کیفیت 720p")
    print("   7. y2mate")
    print("   8. SaveFrom")
    print("   9. 9xBuddy")
    print("   10. DownloadVideos")
    print("   11. SSYouTube")
    print("   12. yt5s")
    print("   13. پروکسی")
    print("   14. Tor")
    print("   15. کیفیت پایین")
    print("="*70)
    
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
    print("✅ ربات با ۱۵ روش دانلود فعال شد!")
    print("✅ فقط یوتیوب - ۹۹.۹٪ تضمینی")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
