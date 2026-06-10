# -*- coding: utf-8 -*-
"""
ربات دانلود هوشمند Ultimate
پشتیبانی کامل از: YouTube, Instagram, Twitter/X, TikTok, Pinterest, Facebook, 
Reddit, Vimeo, SoundCloud, Twitch, Spotify و 1000+ سایت دیگر
با yt-dlp + gallery-dl + Instaloader + spotDL + FFmpeg
"""

import os
import re
import time
import threading
import subprocess
import random
import hashlib
import shutil
from collections import deque
from queue import Queue, Empty, Full
from datetime import datetime
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# تلاش برای import کتابخانه‌های اضافی (در صورت نصب بودن)
try:
    import instaloader
    INSTALOADER_AVAILABLE = True
except ImportError:
    INSTALOADER_AVAILABLE = False

try:
    import gallery_dl
    GALLERY_DL_AVAILABLE = True
except ImportError:
    GALLERY_DL_AVAILABLE = False

try:
    import spotdl
    SPOTDL_AVAILABLE = True
except ImportError:
    SPOTDL_AVAILABLE = False

# ================= تنظیمات اصلی =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 100 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
COOKIE_PATH = "cookies.txt"
PORT = int(os.getenv("PORT", 8080))
REQUIRED_CHANNEL = "@top_topy_downloader"
CHANNEL_LINK = "https://t.me/top_topy_downloader"

# تنظیمات پیشرفته
MAX_WORKERS = 3
MAX_QUEUE_SIZE = 20
MAX_DOWNLOADS_PER_MINUTE = 3
DOWNLOAD_RETRIES = 20
FRAGMENT_RETRIES = 20
CONCURRENT_FRAGMENTS = 8
SOCKET_TIMEOUT = 30

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= کش =================
cache = {}
cache_lock = threading.RLock()

def set_cache(key, value, ttl=3600):
    with cache_lock:
        cache[key] = (value, time.time(), ttl)

def get_cache(key):
    with cache_lock:
        if key in cache:
            val, ts, ttl = cache[key]
            if time.time() - ts < ttl:
                return val
            del cache[key]
    return None

# ================= صف =================
download_queue = Queue(maxsize=MAX_QUEUE_SIZE)
active_downloads = {}
active_lock = threading.Lock()
user_rate_limit = {}
rate_lock = threading.Lock()
pending_links = {}
pending_lock = threading.Lock()
stats = {'total': 0, 'today': 0, 'users': set()}

# ================= User-Agent =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 Chrome/120.0.0.0",
]

def get_ua():
    return random.choice(USER_AGENTS)

# ================= بررسی FFmpeg =================
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        return True
    except:
        return False

FFMPEG_OK = check_ffmpeg()

# ================= تنظیمات yt-dlp پیشرفته =================
def get_ytdlp_opts(quality='best', is_audio=False, progress_callback=None):
    """تنظیمات بهینه yt-dlp برای دانلود حرفه‌ای"""
    
    if is_audio:
        format_spec = 'bestaudio/best'
    elif quality == 'best':
        format_spec = 'bv*+ba/b'
    else:
        format_spec = f'bestvideo[height<={quality}]+bestaudio/best'
    
    opts = {
        'format': format_spec,
        'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s_%(id)s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': DOWNLOAD_RETRIES,
        'fragment_retries': FRAGMENT_RETRIES,
        'concurrent_fragment_downloads': CONCURRENT_FRAGMENTS,
        'socket_timeout': SOCKET_TIMEOUT,
        'user_agent': get_ua(),
        'extractor_args': {
            'youtube': {'player_client': ['android', 'ios', 'web']},
            'instagram': {'video': ['yes']},
            'tiktok': {'video': ['yes']},
        },
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'nocheckcertificate': True,
        'continuedl': True,
        'overwrites': False,
    }
    
    # اضافه کردن کوکی در صورت وجود
    if os.path.exists(COOKIE_PATH):
        opts['cookiefile'] = COOKIE_PATH
    
    # اضافه کردن FFmpeg برای ترکیب صدا و تصویر
    if FFMPEG_OK:
        opts['merge_output_format'] = 'mp4'
    
    # اضافه کردن progress hook
    if progress_callback:
        last_pct = 0
        def hook(d):
            nonlocal last_pct
            if d['status'] == 'downloading':
                pct = d.get('_percent_str', '0%').replace('%', '').strip()
                try:
                    p = float(pct)
                    if p - last_pct >= 10 or p == 100:
                        last_pct = p
                        progress_callback(f"⬇️ {p:.0f}%")
                except:
                    pass
            elif d['status'] == 'finished':
                progress_callback("✅ در حال نهایی‌سازی...")
        opts['progress_hooks'] = [hook]
    
    # تنظیمات صوتی
    if is_audio and FFMPEG_OK:
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    
    return opts

# ================= دانلودر اینستاگرام پیشرفته =================
class InstagramDownloader:
    def __init__(self):
        self.loader = None
        if INSTALOADER_AVAILABLE:
            self.loader = instaloader.Instaloader(
                download_videos=True,
                download_pictures=True,
                compress_json=False,
                post_metadata_txt=False,
                max_connection_attempts=3
            )
    
    def download(self, url, progress_callback=None):
        # روش 1: yt-dlp
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"ig_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'Instagram (yt-dlp)', 'type': 'video'}
        except Exception as e:
            print(f"Instagram yt-dlp error: {e}")
        
        # روش 2: instaloader (در صورت وجود)
        if self.loader:
            try:
                shortcode = re.search(r'/p/([^/]+)/|/reel/([^/]+)/|/tv/([^/]+)/', url)
                if shortcode:
                    code = shortcode.group(1) or shortcode.group(2) or shortcode.group(3)
                    post = instaloader.Post.from_shortcode(self.loader.context, code)
                    if post.is_video:
                        video_url = post.video_url
                        unique = f"{int(time.time()*1000)}"
                        filename = os.path.join(DOWNLOAD_PATH, f"insta_{unique}.mp4")
                        r = requests.get(video_url, headers={'User-Agent': get_ua()}, stream=True)
                        if r.status_code == 200:
                            with open(filename, 'wb') as f:
                                for chunk in r.iter_content(8192):
                                    if chunk:
                                        f.write(chunk)
                            if os.path.getsize(filename) > 10240:
                                return {'file': filename, 'method': 'Instagram (Instaloader)', 'type': 'video'}
            except Exception as e:
                print(f"Instaloader error: {e}")
        
        return None

# ================= دانلودر پینترست =================
class PinterestDownloader:
    def download(self, url, progress_callback=None):
        # روش 1: yt-dlp
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"pin_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                    is_video = filename.lower().endswith(('.mp4', '.mkv', '.webm'))
                    return {'file': filename, 'method': 'Pinterest (yt-dlp)', 'type': 'video' if is_video else 'image'}
        except Exception as e:
            print(f"Pinterest yt-dlp error: {e}")
        
        # روش 2: استخراج مستقیم
        try:
            pin_id = re.search(r'/pin/(\d+)/', url)
            if not pin_id:
                r = requests.get(url, allow_redirects=True)
                pin_id = re.search(r'/pin/(\d+)/', r.url)
            if pin_id:
                api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id.group(1)}"
                headers = {'User-Agent': get_ua(), 'Accept': 'application/json'}
                r = requests.get(api_url, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if data.get('data') and len(data['data']) > 0:
                        images = data['data'][0].get('images', {})
                        for quality in ['orig', '736x', '564x']:
                            if quality in images:
                                img_url = images[quality]['url']
                                unique = f"{int(time.time()*1000)}"
                                filename = os.path.join(DOWNLOAD_PATH, f"pin_{unique}.jpg")
                                img_r = requests.get(img_url, headers=headers, stream=True)
                                if img_r.status_code == 200:
                                    with open(filename, 'wb') as f:
                                        for chunk in img_r.iter_content(8192):
                                            if chunk:
                                                f.write(chunk)
                                    if os.path.getsize(filename) > 1024:
                                        return {'file': filename, 'method': 'Pinterest (API)', 'type': 'image'}
        except Exception as e:
            print(f"Pinterest API error: {e}")
        
        return None

# ================= دانلودر توییتر/X =================
class TwitterDownloader:
    def download(self, url, progress_callback=None):
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"tw_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'Twitter (yt-dlp)', 'type': 'video'}
        except Exception as e:
            print(f"Twitter error: {e}")
        return None

# ================= دانلودر تیک‌تاک =================
class TikTokDownloader:
    def download(self, url, progress_callback=None):
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"tt_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'TikTok (yt-dlp)', 'type': 'video'}
        except Exception as e:
            print(f"TikTok error: {e}")
        return None

# ================= دانلودر ردیت =================
class RedditDownloader:
    def download(self, url, progress_callback=None):
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"rd_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'Reddit (yt-dlp)', 'type': 'video'}
        except Exception as e:
            print(f"Reddit error: {e}")
        return None

# ================= دانلودر فیسبوک =================
class FacebookDownloader:
    def download(self, url, progress_callback=None):
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"fb_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', False, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'Facebook (yt-dlp)', 'type': 'video'}
        except Exception as e:
            print(f"Facebook error: {e}")
        return None

# ================= دانلودر ساوندکلاود =================
class SoundCloudDownloader:
    def download(self, url, is_audio=False, progress_callback=None):
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"sc_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', is_audio, progress_callback)
            opts['outtmpl'] = output
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if is_audio and FFMPEG_OK:
                    filename = os.path.splitext(filename)[0] + '.mp3'
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'method': 'SoundCloud', 'type': 'audio' if is_audio else 'video'}
        except Exception as e:
            print(f"SoundCloud error: {e}")
        return None

# ================= دانلودر اسپاتیفای =================
class SpotifyDownloader:
    def download(self, url, progress_callback=None):
        # روش 1: spotDL (در صورت وجود)
        if SPOTDL_AVAILABLE:
            try:
                unique = f"{int(time.time()*1000)}"
                output_dir = os.path.join(DOWNLOAD_PATH, f"spotify_{unique}")
                os.makedirs(output_dir, exist_ok=True)
                result = subprocess.run(['spotdl', url, '--output', output_dir], 
                                      capture_output=True, timeout=120)
                if result.returncode == 0:
                    for f in os.listdir(output_dir):
                        if f.endswith('.mp3'):
                            filepath = os.path.join(output_dir, f)
                            shutil.move(filepath, os.path.join(DOWNLOAD_PATH, f))
                            shutil.rmtree(output_dir)
                            return {'file': os.path.join(DOWNLOAD_PATH, f), 'method': 'Spotify (spotDL)', 'type': 'audio'}
            except Exception as e:
                print(f"SpotDL error: {e}")
        
        # روش 2: جستجو و دانلود از یوتیوب
        try:
            unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
            output = os.path.join(DOWNLOAD_PATH, f"spotify_{unique}.%(ext)s")
            opts = get_ytdlp_opts('best', True, progress_callback)
            opts['outtmpl'] = output
            # استخراج نام آهنگ از URL
            track_name = re.search(r'track/([^/?]+)', url)
            if track_name:
                query = track_name.group(1).replace('-', ' ')
                search_url = f"ytsearch1:{query}"
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.extract_info(search_url, download=True)
                    filename = ydl.prepare_filename(info)
                    filename = os.path.splitext(filename)[0] + '.mp3'
                    if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                        return {'file': filename, 'method': 'Spotify (via YouTube)', 'type': 'audio'}
        except Exception as e:
            print(f"Spotify search error: {e}")
        
        return None

# ================= دانلودر عمومی با yt-dlp =================
def download_general(url, quality='720', is_audio=False, progress_callback=None):
    try:
        unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
        output = os.path.join(DOWNLOAD_PATH, f"dl_{unique}.%(ext)s")
        opts = get_ytdlp_opts(quality, is_audio, progress_callback)
        opts['outtmpl'] = output
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio and FFMPEG_OK:
                filename = os.path.splitext(filename)[0] + '.mp3'
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                return {'file': filename, 'method': 'yt-dlp', 'type': 'audio' if is_audio else 'video'}
    except Exception as e:
        print(f"General download error: {e}")
    return None

# ================= تشخیص خودکار نوع محتوا =================
def detect_content_type(url):
    url_lower = url.lower()
    
    if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
        return 'image', 'عکس', '🖼️'
    if any(ext in url_lower for ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm']):
        return 'video', 'ویدیو', '🎬'
    if any(ext in url_lower for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']):
        return 'audio', 'آهنگ', '🎵'
    
    if any(d in url_lower for d in ['instagram.com/p/', 'pinterest.com', 'pin.it']):
        return 'image', 'عکس', '🖼️'
    if any(d in url_lower for d in ['soundcloud.com', 'spotify.com']):
        return 'audio', 'آهنگ', '🎵'
    
    return 'video', 'ویدیو', '🎬'

def detect_platform(url):
    u = url.lower()
    if 'youtube.com' in u or 'youtu.be' in u:
        return 'یوتیوب'
    if 'instagram.com' in u:
        return 'اینستاگرام'
    if 'tiktok.com' in u or 'vt.tiktok.com' in u:
        return 'تیک‌تاک'
    if 'twitter.com' in u or 'x.com' in u:
        return 'توییتر/X'
    if 'pinterest.com' in u or 'pin.it' in u:
        return 'پینترست'
    if 'facebook.com' in u or 'fb.com' in u:
        return 'فیسبوک'
    if 'reddit.com' in u or 'redd.it' in u:
        return 'ردیت'
    if 'vimeo.com' in u:
        return 'ویمئو'
    if 'soundcloud.com' in u:
        return 'ساوندکلاود'
    if 'spotify.com' in u:
        return 'اسپاتیفای'
    if 'twitch.tv' in u:
        return 'توئیچ'
    return 'سایر'

# ================= تابع اصلی دانلود =================
def download_media(url, quality='720', is_audio=False, progress_callback=None):
    # بررسی کش
    cached = get_cached_file(url, quality)
    if cached:
        ftype = 'audio' if cached.endswith('.mp3') else ('image' if cached.endswith(('.jpg', '.png')) else 'video')
        return {'file': cached, 'type': ftype, 'cached': True}
    
    url_lower = url.lower()
    
    # انتخاب دانلودر مناسب بر اساس پلتفرم
    if 'instagram.com' in url_lower:
        result = InstagramDownloader().download(url, progress_callback)
    elif 'pinterest.com' in url_lower or 'pin.it' in url_lower:
        result = PinterestDownloader().download(url, progress_callback)
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        result = TwitterDownloader().download(url, progress_callback)
    elif 'tiktok.com' in url_lower or 'vt.tiktok.com' in url_lower:
        result = TikTokDownloader().download(url, progress_callback)
    elif 'reddit.com' in url_lower or 'redd.it' in url_lower:
        result = RedditDownloader().download(url, progress_callback)
    elif 'facebook.com' in url_lower or 'fb.com' in url_lower:
        result = FacebookDownloader().download(url, progress_callback)
    elif 'soundcloud.com' in url_lower:
        result = SoundCloudDownloader().download(url, is_audio, progress_callback)
    elif 'spotify.com' in url_lower:
        result = SpotifyDownloader().download(url, progress_callback)
    else:
        result = download_general(url, quality, is_audio, progress_callback)
    
    if result:
        cache_file(result['file'], url, quality)
        return result
    
    return None

# ================= توابع کش فایل =================
def get_cache_key(url, quality):
    return hashlib.md5(f"{url}_{quality}".encode()).hexdigest()[:16]

def get_cached_file(url, quality):
    key = get_cache_key(url, quality)
    for ext in ['.mp4', '.mp3', '.mkv', '.webm', '.jpg', '.jpeg', '.png', '.gif']:
        path = os.path.join(CACHE_PATH, f"{key}{ext}")
        if os.path.exists(path):
            return path
    return None

def cache_file(file_path, url, quality):
    if file_path and os.path.exists(file_path):
        key = get_cache_key(url, quality)
        ext = os.path.splitext(file_path)[1].lower()
        dest = os.path.join(CACHE_PATH, f"{key}{ext}")
        if not os.path.exists(dest):
            try:
                shutil.move(file_path, dest)
            except:
                pass

# ================= توابع کمکی =================
def extract_url(text):
    urls = re.findall(r'https?://[^\s<>()\[\]{}\n]+', text)
    if urls:
        url = urls[0]
        while url and url[-1] in '.,!?;:)]}':
            url = url[:-1]
        return url
    return None

def resolve_short_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url

def is_member(user_id):
    try:
        m = bot.get_chat_member(REQUIRED_CHANNEL, int(user_id))
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

def join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK),
        InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")
    )
    return markup

def check_rate_limit(user_id):
    with rate_lock:
        now = time.time()
        if user_id not in user_rate_limit:
            user_rate_limit[user_id] = deque(maxlen=MAX_DOWNLOADS_PER_MINUTE)
        q = user_rate_limit[user_id]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= MAX_DOWNLOADS_PER_MINUTE:
            return False, 60 - int(now - q[0])
        q.append(now)
        return True, None

def safe_send(chat_id, file_path, caption, file_type):
    try:
        with open(file_path, 'rb') as f:
            if file_type == 'image':
                return bot.send_photo(chat_id, f, caption=caption, timeout=120)
            elif file_type == 'audio':
                return bot.send_audio(chat_id, f, caption=caption, timeout=120)
            else:
                try:
                    return bot.send_video(chat_id, f, caption=caption, timeout=120)
                except:
                    f.seek(0)
                    return bot.send_document(chat_id, f, caption=caption, timeout=120)
    except Exception as e:
        print(f"Send error: {e}")
        return None

def safe_edit(text, chat_id, msg_id):
    try:
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown')
    except:
        pass

# ================= پردازش دانلود =================
def process_download(user_id, chat_id, url, quality, is_audio, msg_id):
    file_path = None
    result = None
    
    def progress(msg):
        safe_edit(f"🔄 {msg}", chat_id, msg_id)
    
    try:
        safe_edit("🔍 در حال آماده‌سازی...", chat_id, msg_id)
        result = download_media(url, quality, is_audio, progress)
        
        if result and result.get('file') and os.path.exists(result['file']):
            file_path = result['file']
            size = os.path.getsize(file_path)
            
            if size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE//(1024*1024)} مگابایت!")
                return
            
            with active_lock:
                stats['total'] += 1
                stats['today'] += 1
                stats['users'].add(user_id)
            
            type_name = {'image': 'تصویر', 'video': 'ویدیو', 'audio': 'آهنگ'}.get(result['type'], 'فایل')
            q_name = {'360': '360p', '720': '720p', '1080': '1080p', 'best': 'Best', 'audio': 'MP3'}.get(quality, '')
            q_text = f" ({q_name})" if q_name else ""
            caption = f"✅ {type_name}{q_text} دانلود شد!\n📥 {result.get('method', 'دانلودر')}\n📊 {size/(1024*1024):.1f}MB"
            
            safe_send(chat_id, file_path, caption, result['type'])
            safe_edit("✅ انجام شد!", chat_id, msg_id)
        else:
            bot.send_message(chat_id, "❌ خطا در دانلود!")
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطا: {str(e)[:100]}")
    finally:
        if file_path and result and not result.get('cached') and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        with active_lock:
            active_downloads.pop(user_id, None)

def queue_worker():
    while True:
        try:
            task = download_queue.get(timeout=30)
            if task:
                process_download(*task)
                download_queue.task_done()
        except Empty:
            continue
        except Exception as e:
            print(f"Worker error: {e}")

for _ in range(MAX_WORKERS):
    threading.Thread(target=queue_worker, daemon=True).start()

# ================= دستورات بات =================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if not is_member(uid):
        bot.reply_to(message, "🔒 ابتدا در کانال عضو شوید.", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    status = ""
    status += f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}\n"
    status += f"📷 Instaloader: {'✅' if INSTALOADER_AVAILABLE else '❌'}\n"
    status += f"🖼️ Gallery-DL: {'✅' if GALLERY_DL_AVAILABLE else '❌'}\n"
    status += f"🎵 SpotDL: {'✅' if SPOTDL_AVAILABLE else '❌'}\n"
    
    welcome = (
        "🎬 **ربات دانلود هوشمند Ultimate**\n\n"
        "✅ پشتیبانی از 1000+ سایت\n"
        "✅ YouTube | Instagram | Twitter/X | TikTok | Pinterest\n"
        "✅ Facebook | Reddit | Vimeo | SoundCloud | Spotify\n"
        "✅ تشخیص خودکار فیلم / آهنگ / عکس\n"
        f"{status}\n"
        f"📥 حداکثر حجم: {MAX_FILE_SIZE//(1024*1024)}MB\n\n"
        "📌 لینک را بفرستید..."
    )
    bot.reply_to(message, welcome, parse_mode="Markdown")

@bot.message_handler(content_types=['text'])
def handle_msg(message):
    uid = message.from_user.id
    
    if not is_member(uid):
        with pending_lock:
            pending_links[uid] = message.text
        bot.reply_to(message, "🔒 ابتدا عضو کانال شوید.", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    with active_lock:
        if uid in active_downloads:
            bot.reply_to(message, "⏳ در حال دانلود...")
            return
    
    allowed, rem = check_rate_limit(uid)
    if not allowed:
        bot.reply_to(message, f"🛡️ {rem} ثانیه صبر کنید.")
        return
    
    if download_queue.qsize() >= MAX_QUEUE_SIZE:
        bot.reply_to(message, "⚠️ صف پر است!")
        return
    
    url = extract_url(message.text)
    if not url:
        bot.reply_to(message, "❌ لینک نامعتبر!")
        return
    
    url = resolve_short_url(url)
    platform = detect_platform(url)
    
    msg = bot.send_message(message.chat.id, "🔍 در حال بررسی...", parse_mode="Markdown")
    ctype, cname, cemoji = detect_content_type(url)
    
    info = f"{cemoji} **{cname}**\n📱 {platform}"
    safe_edit(info, message.chat.id, msg.message_id)
    
    is_audio = (ctype == 'audio')
    quality = 'audio' if is_audio else '720'
    
    with active_lock:
        active_downloads[uid] = time.time()
    
    safe_edit(f"🔄 دانلود {cname}...", message.chat.id, msg.message_id)
    
    try:
        download_queue.put((uid, message.chat.id, url, quality, is_audio, msg.message_id), timeout=5)
    except:
        with active_lock:
            active_downloads.pop(uid, None)
        safe_edit("⚠️ خطا!", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    
    if call.data == "check_join":
        mem = is_member(uid)
        if mem:
            bot.answer_callback_query(call.id, "عضویت تایید شد ✅")
            safe_edit("✅ عضویت تایید شد!", cid, call.message.message_id)
            with pending_lock:
                if uid in pending_links:
                    text = pending_links.pop(uid)
                    fake = type('obj', (object,), {
                        'from_user': type('obj', (object,), {'id': uid})(),
                        'chat': type('obj', (object,), {'id': cid})(),
                        'text': text
                    })()
                    handle_msg(fake)
        else:
            bot.answer_callback_query(call.id, "عضو نیستید ❌")
            safe_edit("❌ عضویت تایید نشد!", cid, call.message.message_id)
        return

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    with active_lock:
        active = len(active_downloads)
    queue_size = download_queue.qsize()
    cache_files = len([f for f in os.listdir(CACHE_PATH) if os.path.isfile(os.path.join(CACHE_PATH, f))])
    cache_size = sum(os.path.getsize(os.path.join(CACHE_PATH, f)) for f in os.listdir(CACHE_PATH) 
                    if os.path.isfile(os.path.join(CACHE_PATH, f))) / (1024*1024)
    
    text = (
        "👑 **پنل مدیریت Ultimate**\n\n"
        f"👤 کاربران: {len(stats['users'])}\n"
        f"📥 کل دانلودها: {stats['total']}\n"
        f"📅 امروز: {stats['today']}\n"
        f"⚡ فعال: {active}\n"
        f"📋 صف: {queue_size}\n"
        f"💾 کش: {cache_files} فایل / {cache_size:.1f}MB\n"
        f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}\n"
        f"📷 Instaloader: {'✅' if INSTALOADER_AVAILABLE else '❌'}\n"
        f"🎵 SpotDL: {'✅' if SPOTDL_AVAILABLE else '❌'}\n\n"
        f"⚙️ Workers: {MAX_WORKERS} | صف: {MAX_QUEUE_SIZE} | حجم: {MAX_FILE_SIZE//(1024*1024)}MB"
    )
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🗑️ پاک کردن کش", callback_data="admin_clean"),
        InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
        InlineKeyboardButton("🧹 پاکسازی فایل‌ها", callback_data="admin_purge")
    )
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید!")
        return
    
    if call.data == "admin_clean":
        d = 0
        for f in os.listdir(CACHE_PATH):
            try:
                os.remove(os.path.join(CACHE_PATH, f))
                d += 1
            except:
                pass
        bot.answer_callback_query(call.id, f"✅ {d} فایل پاک شد!")
    
    elif call.data == "admin_purge":
        d = 0
        for f in os.listdir(DOWNLOAD_PATH):
            try:
                os.remove(os.path.join(DOWNLOAD_PATH, f))
                d += 1
            except:
                pass
        bot.answer_callback_query(call.id, f"✅ {d} فایل موقت پاک شد!")
    
    elif call.data == "admin_stats":
        with active_lock:
            active = len(active_downloads)
        queue_size = download_queue.qsize()
        cache_f = len([f for f in os.listdir(CACHE_PATH) if os.path.isfile(os.path.join(CACHE_PATH, f))])
        cache_sz = sum(os.path.getsize(os.path.join(CACHE_PATH, f)) for f in os.listdir(CACHE_PATH) 
                      if os.path.isfile(os.path.join(CACHE_PATH, f))) / (1024*1024)
        
        text = (
            "📊 **آمار دقیق**\n\n"
            f"👤 کاربران: {len(stats['users'])}\n"
            f"📥 کل دانلودها: {stats['total']}\n"
            f"📅 امروز: {stats['today']}\n"
            f"⚡ فعال: {active}\n"
            f"📋 صف: {queue_size}\n"
            f"💾 کش: {cache_f} / {cache_sz:.1f}MB"
        )
        safe_edit(text, call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['clean'])
def clean_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    d = 0
    for f in os.listdir(CACHE_PATH):
        try:
            os.remove(os.path.join(CACHE_PATH, f))
            d += 1
        except:
            pass
    bot.reply_to(message, f"✅ {d} فایل پاک شد!")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    with active_lock:
        active = len(active_downloads)
    queue_size = download_queue.qsize()
    bot.reply_to(message, f"📊 آمار\nفعال: {active}\nصف: {queue_size}\nکل: {stats['total']}")

# ================= وب‌هوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(data)
        bot.process_new_updates([update])
        return "OK", 200
    except:
        return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "🎬 ربات دانلود هوشمند Ultimate فعال است!", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "active": len(active_downloads),
        "queue": download_queue.qsize(),
        "total": stats['total'],
        "ffmpeg": FFMPEG_OK
    })

# ================= اجرا =================
def run_polling():
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود هوشمند Ultimate")
    print(f"✅ FFmpeg: {'✅' if FFMPEG_OK else '❌'}")
    print(f"✅ Instaloader: {'✅' if INSTALOADER_AVAILABLE else '❌'}")
    print(f"✅ Gallery-DL: {'✅' if GALLERY_DL_AVAILABLE else '❌'}")
    print(f"✅ SpotDL: {'✅' if SPOTDL_AVAILABLE else '❌'}")
    print(f"✅ Workers: {MAX_WORKERS} | صف: {MAX_QUEUE_SIZE}")
    print("="*60)
    
    try:
        bot.remove_webhook()
        print("✅ Webhook removed")
    except:
        pass
    
    threading.Thread(target=run_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
