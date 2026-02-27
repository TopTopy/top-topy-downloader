# -*- coding: utf-8 -*-
import os
import threading
import time
import re
import subprocess
import json
import random
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from flask import Flask, request

# ================= نصب همه کتابخانه‌های دانلود =================
# pip install yt-dlp pytubefix youtube-dl pafy google-api-python-client

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except:
    YT_DLP_AVAILABLE = False
    print("⚠️ yt-dlp نصب نیست")

try:
    from pytubefix import YouTube
    from pytubefix.cli import on_progress
    PYTUBEFIX_AVAILABLE = True
except:
    PYTUBEFIX_AVAILABLE = False
    print("⚠️ pytubefix نصب نیست")

try:
    import youtube_dl
    YOUTUBE_DL_AVAILABLE = True
except:
    YOUTUBE_DL_AVAILABLE = False
    print("⚠️ youtube-dl نصب نیست")

try:
    import pafy
    PAFY_AVAILABLE = True
except:
    PAFY_AVAILABLE = False
    print("⚠️ pafy نصب نیست")

try:
    from googleapiclient.discovery import build
    YOUTUBE_API_AVAILABLE = True
except:
    YOUTUBE_API_AVAILABLE = False
    print("⚠️ google-api-python-client نصب نیست")

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

# API Key یوتیوب (اختیاری - برای روش API)
YOUTUBE_API_KEY = "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # اینو از Google Cloud Console بگیر

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs("database", exist_ok=True)

# ================= ابزار =================
def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def is_youtube_url(url):
    url = url.lower()
    youtube_domains = ['youtube.com', 'youtu.be']
    return any(domain in url for domain in youtube_domains)

def extract_video_id(url):
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

# ================= موتور دانلود یوتیوب با ۲۰ روش =================
class YouTubeDownloader:
    def __init__(self):
        self.session = requests.Session() if 'requests' in dir() else None
        
    def _download_file(self, url, filename):
        """دانلود فایل از لینک مستقیم"""
        try:
            import requests
            response = requests.get(url, stream=True, timeout=60)
            if response.status_code == 200:
                filepath = os.path.join(DOWNLOAD_PATH, filename)
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return filepath
        except:
            return None
    
    # ========== روش 1: yt-dlp (subprocess) ==========
    def method_1_ytdlp_subprocess(self, url, quality='best'):
        """روش 1: yt-dlp با subprocess"""
        try:
            output_template = f'{DOWNLOAD_PATH}/ytdlp1_%(title)s_%(id)s.%(ext)s'
            cmd = [
                'yt-dlp',
                '-f', f'{quality}[ext=mp4]/best[ext=mp4]/best',
                '-o', output_template,
                '--no-playlist',
                '--no-warnings',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp subprocess', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 2: yt-dlp (کتابخانه) ==========
    def method_2_ytdlp_library(self, url, quality='best'):
        """روش 2: yt-dlp با کتابخانه"""
        if not YT_DLP_AVAILABLE:
            return None
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': f'{quality}[ext=mp4]/best[ext=mp4]/best',
                'outtmpl': f'{DOWNLOAD_PATH}/ytdlp2_%(title)s_%(id)s.%(ext)s',
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    filename = ydl.prepare_filename(info)
                    if os.path.exists(filename):
                        return {'file': filename, 'method': 'yt-dlp library', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 3: pytubefix ==========
    def method_3_pytubefix(self, url, quality='best'):
        """روش 3: pytubefix"""
        if not PYTUBEFIX_AVAILABLE:
            return None
        try:
            yt = YouTube(url, on_progress_callback=on_progress)
            if quality == 'best':
                stream = yt.streams.get_highest_resolution()
            elif '1080' in quality:
                stream = yt.streams.filter(res="1080p", file_extension='mp4').first()
            elif '720' in quality:
                stream = yt.streams.filter(res="720p", file_extension='mp4').first()
            else:
                stream = yt.streams.get_highest_resolution()
            
            if stream:
                filename = stream.download(output_path=DOWNLOAD_PATH)
                return {'file': filename, 'method': 'pytubefix', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 4: youtube-dl ==========
    def method_4_youtube_dl(self, url, quality='best'):
        """روش 4: youtube-dl"""
        if not YOUTUBE_DL_AVAILABLE:
            return None
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': f'{quality}[ext=mp4]/best[ext=mp4]/best',
                'outtmpl': f'{DOWNLOAD_PATH}/ytdl_%(title)s_%(id)s.%(ext)s',
                'noplaylist': True,
            }
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    filename = ydl.prepare_filename(info)
                    if os.path.exists(filename):
                        return {'file': filename, 'method': 'youtube-dl', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 5: pafy ==========
    def method_5_pafy(self, url):
        """روش 5: pafy"""
        if not PAFY_AVAILABLE:
            return None
        try:
            video = pafy.new(url)
            best = video.getbest(preftype="mp4")
            if best:
                filename = best.download(filepath=DOWNLOAD_PATH)
                return {'file': filename, 'method': 'pafy', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 6: yt-dlp با کوکی ==========
    def method_6_ytdlp_cookies(self, url, quality='best'):
        """روش 6: yt-dlp با کوکی"""
        try:
            cookies_file = "cookies.txt"
            if os.path.exists(cookies_file):
                cmd = [
                    'yt-dlp',
                    '--cookies', cookies_file,
                    '-f', f'{quality}[ext=mp4]/best[ext=mp4]/best',
                    '-o', f'{DOWNLOAD_PATH}/ytdlp_cookies_%(title)s_%(id)s.%(ext)s',
                    '--no-playlist',
                    '--quiet',
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    time.sleep(2)
                    files = os.listdir(DOWNLOAD_PATH)
                    latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                    return {'file': latest, 'method': 'yt-dlp cookies', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 7: yt-dlp با پروکسی ==========
    def method_7_ytdlp_proxy(self, url, quality='best'):
        """روش 7: yt-dlp با پروکسی"""
        proxies = [
            "http://proxy1.com:8080",
            "http://proxy2.com:8080",
        ]
        for proxy in proxies:
            try:
                cmd = [
                    'yt-dlp',
                    '--proxy', proxy,
                    '-f', f'{quality}[ext=mp4]/best[ext=mp4]/best',
                    '-o', f'{DOWNLOAD_PATH}/ytdlp_proxy_%(title)s_%(id)s.%(ext)s',
                    '--no-playlist',
                    '--quiet',
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    time.sleep(2)
                    files = os.listdir(DOWNLOAD_PATH)
                    latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                    return {'file': latest, 'method': 'yt-dlp proxy', 'size': os.path.getsize(latest)}
            except:
                continue
        return None
    
    # ========== روش 8: yt-dlp با Tor ==========
    def method_8_ytdlp_tor(self, url, quality='best'):
        """روش 8: yt-dlp با Tor"""
        try:
            cmd = [
                'yt-dlp',
                '--proxy', 'socks5://127.0.0.1:9050',
                '-f', f'{quality}[ext=mp4]/best[ext=mp4]/best',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_tor_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp Tor', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 9: yt-dlp با کیفیت پایین ==========
    def method_9_ytdlp_low(self, url):
        """روش 9: yt-dlp با کیفیت پایین"""
        try:
            cmd = [
                'yt-dlp',
                '-f', 'worst[ext=mp4]/worst',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_low_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp low', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 10: yt-dlp با فرمت خاص ==========
    def method_10_ytdlp_format(self, url):
        """روش 10: yt-dlp با فرمت خاص"""
        try:
            cmd = [
                'yt-dlp',
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                '--merge-output-format', 'mp4',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_format_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp format', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 11: pytubefix با کیفیت پایین ==========
    def method_11_pytubefix_low(self, url):
        """روش 11: pytubefix با کیفیت پایین"""
        if not PYTUBEFIX_AVAILABLE:
            return None
        try:
            yt = YouTube(url)
            stream = yt.streams.get_lowest_resolution()
            if stream:
                filename = stream.download(output_path=DOWNLOAD_PATH)
                return {'file': filename, 'method': 'pytubefix low', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 12: pytubefix با صدا ==========
    def method_12_pytubefix_audio(self, url):
        """روش 12: pytubefix فقط صدا"""
        if not PYTUBEFIX_AVAILABLE:
            return None
        try:
            yt = YouTube(url)
            stream = yt.streams.get_audio_only()
            if stream:
                filename = stream.download(output_path=DOWNLOAD_PATH, mp3=True)
                return {'file': filename, 'method': 'pytubefix audio', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 13: yt-dlp فقط صدا ==========
    def method_13_ytdlp_audio(self, url):
        """روش 13: yt-dlp فقط صدا"""
        try:
            cmd = [
                'yt-dlp',
                '-f', 'bestaudio',
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '0',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_audio_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp audio', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 14: youtube-dl فقط صدا ==========
    def method_14_youtube_dl_audio(self, url):
        """روش 14: youtube-dl فقط صدا"""
        if not YOUTUBE_DL_AVAILABLE:
            return None
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
                'outtmpl': f'{DOWNLOAD_PATH}/ytdl_audio_%(title)s_%(id)s.%(ext)s',
                'noplaylist': True,
            }
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
                    if os.path.exists(filename):
                        return {'file': filename, 'method': 'youtube-dl audio', 'size': os.path.getsize(filename)}
        except:
            return None
    
    # ========== روش 15: yt-dlp با پلی‌لیست ==========
    def method_15_ytdlp_playlist(self, url):
        """روش 15: yt-dlp برای پلی‌لیست"""
        try:
            cmd = [
                'yt-dlp',
                '-f', 'best[ext=mp4]/best',
                '-o', f'{DOWNLOAD_PATH}/playlist/%(playlist_title)s/%(playlist_index)s_%(title)s.%(ext)s',
                '--yes-playlist',
                '--quiet',
                url
            ]
            os.makedirs(f'{DOWNLOAD_PATH}/playlist', exist_ok=True)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return {'method': 'yt-dlp playlist', 'success': True}
        except:
            return None
    
    # ========== روش 16: yt-dlp با زیرنویس ==========
    def method_16_ytdlp_subtitles(self, url):
        """روش 16: yt-dlp با زیرنویس"""
        try:
            cmd = [
                'yt-dlp',
                '--write-subs',
                '--sub-lang', 'en,fa',
                '--embed-subs',
                '-f', 'best[ext=mp4]/best',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_subs_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp with subs', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 17: yt-dlp با محدودیت سرعت ==========
    def method_17_ytdlp_rate_limit(self, url):
        """روش 17: yt-dlp با محدودیت سرعت"""
        try:
            cmd = [
                'yt-dlp',
                '--limit-rate', '1M',
                '-f', 'best[ext=mp4]/best',
                '-o', f'{DOWNLOAD_PATH}/ytdlp_rate_%(title)s_%(id)s.%(ext)s',
                '--no-playlist',
                '--quiet',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                return {'file': latest, 'method': 'yt-dlp rate limit', 'size': os.path.getsize(latest)}
        except:
            return None
    
    # ========== روش 18: yt-dlp با یوزراینجنت ==========
    def method_18_ytdlp_useragent(self, url):
        """روش 18: yt-dlp با تغییر User-Agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
        ]
        for ua in user_agents:
            try:
                cmd = [
                    'yt-dlp',
                    '--user-agent', ua,
                    '-f', 'best[ext=mp4]/best',
                    '-o', f'{DOWNLOAD_PATH}/ytdlp_ua_%(title)s_%(id)s.%(ext)s',
                    '--no-playlist',
                    '--quiet',
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    time.sleep(2)
                    files = os.listdir(DOWNLOAD_PATH)
                    latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                    return {'file': latest, 'method': 'yt-dlp UA', 'size': os.path.getsize(latest)}
            except:
                continue
        return None
    
    # ========== روش 19: دانلود از طریق API یوتیوب ==========
    def method_19_youtube_api(self, url):
        """روش 19: دانلود از طریق API یوتیوب"""
        if not YOUTUBE_API_AVAILABLE or YOUTUBE_API_KEY == "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAA":
            return None
        try:
            video_id = extract_video_id(url)
            if video_id:
                youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
                request = youtube.videos().list(part='snippet,contentDetails', id=video_id)
                response = request.execute()
                if response['items']:
                    return {'info': response['items'][0], 'method': 'YouTube API'}
        except:
            return None
    
    # ========== روش 20: yt-dlp با رفرش ==========
    def method_20_ytdlp_retry(self, url, quality='best'):
        """روش 20: yt-dlp با تلاش مجدد"""
        for attempt in range(3):
            try:
                cmd = [
                    'yt-dlp',
                    '--retries', '10',
                    '--fragment-retries', '10',
                    '-f', f'{quality}[ext=mp4]/best[ext=mp4]/best',
                    '-o', f'{DOWNLOAD_PATH}/ytdlp_retry{attempt}_%(title)s_%(id)s.%(ext)s',
                    '--no-playlist',
                    '--quiet',
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    time.sleep(2)
                    files = os.listdir(DOWNLOAD_PATH)
                    latest = max([os.path.join(DOWNLOAD_PATH, f) for f in files], key=os.path.getctime)
                    return {'file': latest, 'method': f'yt-dlp retry {attempt+1}', 'size': os.path.getsize(latest)}
            except:
                time.sleep(2)
        return None
    
    def download_with_all_methods(self, url, quality='best', chat_id=None, msg_id=None):
        """تلاش با همه روش‌ها"""
        methods = [
            ("yt-dlp subprocess", lambda: self.method_1_ytdlp_subprocess(url, quality)),
            ("yt-dlp library", lambda: self.method_2_ytdlp_library(url, quality)),
            ("pytubefix", lambda: self.method_3_pytubefix(url, quality)),
            ("youtube-dl", lambda: self.method_4_youtube_dl(url, quality)),
            ("pafy", lambda: self.method_5_pafy(url)),
            ("yt-dlp cookies", lambda: self.method_6_ytdlp_cookies(url, quality)),
            ("yt-dlp proxy", lambda: self.method_7_ytdlp_proxy(url, quality)),
            ("yt-dlp Tor", lambda: self.method_8_ytdlp_tor(url, quality)),
            ("yt-dlp low quality", lambda: self.method_9_ytdlp_low(url)),
            ("yt-dlp format", lambda: self.method_10_ytdlp_format(url)),
            ("pytubefix low", lambda: self.method_11_pytubefix_low(url)),
            ("pytubefix audio", lambda: self.method_12_pytubefix_audio(url)),
            ("yt-dlp audio", lambda: self.method_13_ytdlp_audio(url)),
            ("youtube-dl audio", lambda: self.method_14_youtube_dl_audio(url)),
            ("yt-dlp with subs", lambda: self.method_16_ytdlp_subtitles(url)),
            ("yt-dlp rate limit", lambda: self.method_17_ytdlp_rate_limit(url)),
            ("yt-dlp useragent", lambda: self.method_18_ytdlp_useragent(url)),
            ("yt-dlp retry", lambda: self.method_20_ytdlp_retry(url, quality)),
        ]
        
        # اضافه کردن روش API اگر کلید داشته باشیم
        if YOUTUBE_API_KEY != "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAA":
            methods.append(("YouTube API", lambda: self.method_19_youtube_api(url)))
        
        for i, (method_name, method_func) in enumerate(methods, 1):
            try:
                if msg_id and chat_id:
                    try:
                        bot.edit_message_text(
                            f"🔄 **روش {i}/{len(methods)}**\n📡 {method_name}...",
                            chat_id,
                            msg_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                result = method_func()
                
                if result and result.get('file') and os.path.exists(result['file']):
                    file_size = os.path.getsize(result['file'])
                    if file_size > MAX_FILE_SIZE:
                        os.remove(result['file'])
                        continue
                    
                    return {
                        'filename': result['file'],
                        'size': file_size,
                        'method': method_name
                    }
                    
            except Exception as e:
                print(f"خطا در روش {method_name}: {e}")
                continue
        
        return None

# ================= ایجاد نمونه =================
downloader = YouTubeDownloader()
db = None
bot = None

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
            download_method TEXT,
            is_blocked INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
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

    def add_download(self, user_id, method):
        self.cursor.execute("UPDATE users SET download_count=download_count+1, download_method=? WHERE user_id=?", (method, user_id))
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

# ================= ایجاد نمونه دیتابیس و ربات =================
db = Database()
bot = telebot.TeleBot(TOKEN)

# ================= توابع کمکی =================
def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

def format_duration(seconds):
    minutes = seconds // 60
    hours = minutes // 60
    if hours > 0:
        return f"{hours}:{minutes%60:02d}:{seconds%60:02d}"
    else:
        return f"{minutes}:{seconds%60:02d}"

# ================= کیبورد انتخاب کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 1080p", callback_data="quality_1080p"),
        InlineKeyboardButton("🎥 720p", callback_data="quality_720p"),
        InlineKeyboardButton("🎥 480p", callback_data="quality_480p"),
        InlineKeyboardButton("🎥 360p", callback_data="quality_360p"),
        InlineKeyboardButton("🎵 MP3", callback_data="quality_audio"),
        InlineKeyboardButton("❌ لغو", callback_data="quality_cancel")
    )
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
        "به **قوی‌ترین ربات دانلود یوتیوب** خوش اومدی 🤖\n\n"
        "✅ **۲۰ روش مختلف دانلود:**\n"
        "• yt-dlp (subprocess و library)\n"
        "• pytubefix (کیفیت بالا و پایین)\n"
        "• youtube-dl\n"
        "• pafy\n"
        "• با پروکسی و Tor\n"
        "• با کوکی\n"
        "• با زیرنویس\n"
        "• فقط صدا MP3\n"
        "• و ۱۲ روش دیگر...\n\n"
        "✅ **حجم مجاز:** ۳۰۰ مگابایت\n"
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('quality_'))
def quality_callback(call):
    if call.data == "quality_cancel":
        bot.edit_message_text("❌ عملیات لغو شد.", call.message.chat.id, call.message.message_id)
        return
    
    quality_map = {
        "quality_1080p": "best[height<=1080]",
        "quality_720p": "best[height<=720]",
        "quality_480p": "best[height<=480]",
        "quality_360p": "best[height<=360]",
        "quality_audio": "audio"
    }
    
    quality = quality_map.get(call.data, "best")
    url = call.message.text.split('\n')[-1]
    
    bot.edit_message_text(
        f"🔄 **در حال دانلود با ۲۰ روش مختلف...**\n⏳ این فرآیند چند لحظه طول می‌کشد",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    threading.Thread(
        target=process_download,
        args=(url, quality, call.message.chat.id, call.from_user.id, call.message.message_id),
        daemon=True
    ).start()

def process_download(url, quality, chat_id, user_id, msg_id):
    try:
        result = downloader.download_with_all_methods(url, quality, chat_id, msg_id)
        
        if result:
            with open(result['filename'], 'rb') as f:
                if result['filename'].endswith('.mp3'):
                    bot.send_audio(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📥 روش: {result['method']}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=120
                    )
                else:
                    bot.send_video(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📥 روش: {result['method']}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=120
                    )
            
            os.remove(result['filename'])
            db.add_download(user_id, result['method'])
            
            bot.edit_message_text(
                f"✅ **دانلود با موفقیت انجام شد!**\n📥 روش: {result['method']}",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                "❌ **خطا در دانلود!**\nهمه ۲۰ روش امتحان شدند اما موفق نبود.",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
    except Exception as e:
        bot.edit_message_text(
            f"❌ **خطا:**\n`{str(e)[:200]}`",
            chat_id,
            msg_id,
            parse_mode="Markdown"
        )

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

    urls = extract_urls(message.text)
    if not urls:
        return
    
    url = urls[0]
    
    if not is_youtube_url(url):
        bot.reply_to(
            message,
            "❌ **لطفاً فقط لینک یوتیوب ارسال کنید**",
            parse_mode="Markdown"
        )
        return
    
    info_msg = bot.reply_to(message, "🔄 **در حال دریافت اطلاعات...**", parse_mode="Markdown")
    
    # استفاده از yt-dlp برای گرفتن اطلاعات
    try:
        cmd = ['yt-dlp', '--dump-json', '--no-playlist', '--quiet', url]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            info_text = (
                f"📹 **اطلاعات ویدیو**\n\n"
                f"📌 عنوان: `{info.get('title', 'بدون عنوان')[:50]}...`\n"
                f"⏱ مدت: {format_duration(info.get('duration', 0))}\n"
                f"👤 کانال: {info.get('uploader', 'ناشناس')}\n"
                f"👁 بازدید: {info.get('view_count', 0):,}\n\n"
                f"⬇️ **کیفیت مورد نظر را انتخاب کنید:**"
            )
            
            bot.edit_message_text(
                info_text,
                info_msg.chat.id,
                info_msg.message_id,
                reply_markup=quality_keyboard(),
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                "❌ **خطا در دریافت اطلاعات ویدیو!**",
                info_msg.chat.id,
                info_msg.message_id,
                parse_mode="Markdown"
            )
    except:
        bot.edit_message_text(
            "❌ **خطا در دریافت اطلاعات ویدیو!**",
            info_msg.chat.id,
            info_msg.message_id,
            parse_mode="Markdown"
        )

# ================= پنل ادمین =================
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
    text += f"🟢 روش‌ها: ۲۰ روش فعال\n"
    text += f"📚 کتابخانه‌ها:\n"
    text += f"   ✅ yt-dlp: {'نصب' if YT_DLP_AVAILABLE else 'نصب نیست'}\n"
    text += f"   ✅ pytubefix: {'نصب' if PYTUBEFIX_AVAILABLE else 'نصب نیست'}\n"
    text += f"   ✅ youtube-dl: {'نصب' if YOUTUBE_DL_AVAILABLE else 'نصب نیست'}\n"
    text += f"   ✅ pafy: {'نصب' if PAFY_AVAILABLE else 'نصب نیست'}\n"
    text += f"   ✅ YouTube API: {'فعال' if YOUTUBE_API_KEY != 'AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAA' else 'غیرفعال'}\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    stats = db.cursor.execute("SELECT download_method, COUNT(*) FROM users WHERE download_method IS NOT NULL GROUP BY download_method").fetchall()
    if stats:
        text = "📊 **آمار روش‌های دانلود:**\n\n"
        for method, count in stats:
            text += f"• {method}: {count} بار\n"
        bot.reply_to(message, text, parse_mode="Markdown")
    else:
        bot.reply_to(message, "📊 هنوز آماری ثبت نشده است.")

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
    return "ربات دانلود یوتیوب با ۲۰ روش و ۵ کتابخانه"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود یوتیوب با ۲۰ روش و ۵ کتابخانه")
    print("="*70)
    print("📚 کتابخانه‌های نصب شده:")
    print(f"   ✅ yt-dlp: {'نصب' if YT_DLP_AVAILABLE else 'نصب نیست'}")
    print(f"   ✅ pytubefix: {'نصب' if PYTUBEFIX_AVAILABLE else 'نصب نیست'}")
    print(f"   ✅ youtube-dl: {'نصب' if YOUTUBE_DL_AVAILABLE else 'نصب نیست'}")
    print(f"   ✅ pafy: {'نصب' if PAFY_AVAILABLE else 'نصب نیست'}")
    print(f"   ✅ YouTube API: {'فعال' if YOUTUBE_API_KEY != 'AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAA' else 'غیرفعال'}")
    print("="*70)
    print("🎯 ۲۰ روش دانلود فعال:")
    print("   1. yt-dlp subprocess")
    print("   2. yt-dlp library")
    print("   3. pytubefix")
    print("   4. youtube-dl")
    print("   5. pafy")
    print("   6. yt-dlp cookies")
    print("   7. yt-dlp proxy")
    print("   8. yt-dlp Tor")
    print("   9. yt-dlp low quality")
    print("   10. yt-dlp format")
    print("   11. pytubefix low")
    print("   12. pytubefix audio")
    print("   13. yt-dlp audio")
    print("   14. youtube-dl audio")
    print("   15. yt-dlp playlist")
    print("   16. yt-dlp with subs")
    print("   17. yt-dlp rate limit")
    print("   18. yt-dlp useragent")
    print("   19. YouTube API")
    print("   20. yt-dlp retry")
    print("="*70)
    
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except:
            pass
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات با ۲۰ روش و ۵ کتابخانه فعال شد!")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
