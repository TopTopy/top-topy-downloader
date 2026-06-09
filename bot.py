# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import json
import subprocess
import random
from datetime import datetime
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات (بدون متغیر محیطی) =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 500 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://web-production-d8a05.up.railway.app/webhook"
PORT = 8080
REQUIRED_CHANNEL = "@top_topy_downloader"

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = {}
pending_links = {}
lock = threading.Lock()

# ================= User-Agent های مختلف =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ================= بررسی عضویت در کانال =================
def is_member(user_id):
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Error checking membership for {user_id}: {e}")
        return False

# ================= دکمه عضویت =================
def join_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "📢 عضویت در کانال",
            url="https://t.me/top_topy_downloader"
        )
    )
    markup.add(
        InlineKeyboardButton(
            "✅ عضو شدم",
            callback_data="check_join"
        )
    )
    return markup

# ================= تشخیص خودکار نوع محتوا =================
def detect_content_type(url):
    """تشخیص خودکار اینکه لینک شامل چه نوع محتوایی است"""
    url_lower = url.lower()
    
    # تشخیص از روی پسوند فایل
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.jfif', '.ico']
    video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp']
    audio_extensions = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma', '.opus']
    
    for ext in image_extensions:
        if ext in url_lower:
            return 'image', 'عکس'
    for ext in video_extensions:
        if ext in url_lower:
            return 'video', 'ویدیو'
    for ext in audio_extensions:
        if ext in url_lower:
            return 'audio', 'آهنگ'
    
    # تشخیص از روی دامنه
    image_domains = ['instagram.com/p/', 'instagram.com/reel/', 'pinterest.com', 'pin.it', 'flickr.com', 'imgur.com']
    for domain in image_domains:
        if domain in url_lower:
            return 'image', 'عکس'
    
    audio_domains = ['soundcloud.com', 'spotify.com', 'music.apple.com', 'deezer.com']
    for domain in audio_domains:
        if domain in url_lower:
            return 'audio', 'آهنگ'
    
    # بررسی با yt-dlp
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'simulate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            has_video = any(f.get('vcodec') != 'none' and f.get('vcodec') for f in formats)
            has_audio = any(f.get('acodec') != 'none' and f.get('acodec') for f in formats)
            
            if has_video:
                return 'video', 'ویدیو'
            elif has_audio and not has_video:
                return 'audio', 'آهنگ'
    except Exception as e:
        print(f"Error detecting content type: {e}")
    
    return 'video', 'ویدیو'

# ================= کیبورد خودکار =================
def auto_keyboard(content_type):
    markup = InlineKeyboardMarkup(row_width=2)
    
    if content_type == 'image':
        markup.add(
            InlineKeyboardButton("🖼️ دانلود عکس", callback_data="image"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        )
    elif content_type == 'audio':
        markup.add(
            InlineKeyboardButton("🎵 دانلود آهنگ", callback_data="audio"),
            InlineKeyboardButton("🎥 دانلود ویدیو (در صورت وجود)", callback_data="video"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        )
    else:
        markup.add(
            InlineKeyboardButton("🎥 دانلود ویدیو", callback_data="video"),
            InlineKeyboardButton("🎵 دانلود صدا", callback_data="audio"),
            InlineKeyboardButton("🖼️ دانلود عکس (کاور)", callback_data="image"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel")
        )
    return markup

# ================= تشخیص پلتفرم =================
def detect_platform(url):
    url = url.lower()
    platforms = {
        'یوتیوب': ['youtube.com', 'youtu.be'],
        'اینستاگرام': ['instagram.com', 'instagr.am'],
        'تیک‌تاک': ['tiktok.com', 'vt.tiktok.com'],
        'توییتر': ['twitter.com', 'x.com'],
        'فیسبوک': ['facebook.com', 'fb.com', 'fb.watch'],
        'پینترست': ['pinterest.com', 'pin.it'],
        'ساوندکلاود': ['soundcloud.com'],
        'اسپاتیفای': ['spotify.com'],
        'آپارات': ['aparat.com'],
        'تلوبیون': ['telewebion.com'],
        'فیلیمو': ['filimo.com', 'filimo.ir'],
        'نماشا': ['namasha.com'],
        'کلپس': ['clips.ir'],
        'تماشا': ['tamasha.com'],
    }
    
    for platform, domains in platforms.items():
        for domain in domains:
            if domain in url:
                return platform
    return "سایر"

# ================= ابزار لینک =================
def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def resolve_short_url(url):
    try:
        short_domains = ['bit.ly', 'tinyurl.com', 't.co', 'rb.gy', 'ow.ly', 'is.gd', 'buff.ly', 'pin.it']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10, headers={'User-Agent': random.choice(USER_AGENTS)})
            return response.url
        return url
    except Exception as e:
        print(f"Error resolving short URL: {e}")
        return url

# ================= دانلود مستقیم تصویر =================
def download_image_direct(url):
    try:
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        
        ext = '.jpg'
        for known_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            if known_ext in url.lower():
                ext = known_ext
                break
        
        filename = os.path.join(DOWNLOAD_PATH, f"image_{unique}{ext}")
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        response = requests.get(url, headers=headers, timeout=30, stream=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'image' in content_type:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                    return {'file': filename, 'method': 'دانلود مستقیم تصویر', 'type': 'image'}
        return None
    except Exception as e:
        print(f"خطا در دانلود تصویر: {e}")
        return None

# ================= دانلود آپارات =================
def download_aparat(url):
    try:
        video_id = None
        patterns = [
            r'aparat\.com/v/([a-zA-Z0-9]+)',
            r'aparat\.com/([a-zA-Z0-9]+)',
            r'i\.aparat\.com/([a-zA-Z0-9]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        if video_id:
            api_url = f"https://www.aparat.com/etc/api/video/videoID/{video_id}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'video' in data:
                    video_url = data['video'].get('file')
                    if video_url:
                        unique = str(int(time.time()*1000))
                        filename = os.path.join(DOWNLOAD_PATH, f"aparat_{unique}.mp4")
                        video_response = requests.get(video_url, headers=headers, stream=True, timeout=60)
                        
                        if video_response.status_code == 200:
                            with open(filename, 'wb') as f:
                                for chunk in video_response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                            
                            if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                                return {'file': filename, 'method': 'آپارات', 'type': 'video'}
    except Exception as e:
        print(f"خطا در دانلود آپارات: {e}")
    return None

# ================= دانلود تلوبیون =================
def download_telewebion(url):
    try:
        program_id = re.search(r'telewebion\.com/program/(\d+)', url)
        if program_id:
            program_id = program_id.group(1)
            api_url = f"https://www.telewebion.com/api/program/{program_id}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'video_url' in data['data']:
                    video_url = data['data']['video_url']
                    if video_url:
                        unique = str(int(time.time()*1000))
                        filename = os.path.join(DOWNLOAD_PATH, f"telewebion_{unique}.mp4")
                        video_response = requests.get(video_url, headers=headers, stream=True, timeout=60)
                        
                        if video_response.status_code == 200:
                            with open(filename, 'wb') as f:
                                for chunk in video_response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                            
                            if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                                return {'file': filename, 'method': 'تلوبیون', 'type': 'video'}
    except Exception as e:
        print(f"خطا در دانلود تلوبیون: {e}")
    return None

# ================= دانلود فیلیمو =================
def download_filimo(url):
    try:
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"filimo_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 10,
            'user_agent': random.choice(USER_AGENTS),
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                return {'file': filepath, 'method': 'فیلیمو', 'type': 'video'}
    except Exception as e:
        print(f"خطا در دانلود فیلیمو: {e}")
    return None

# ================= دانلود نماشا =================
def download_namasha(url):
    try:
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"namasha_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 10,
            'user_agent': random.choice(USER_AGENTS),
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                return {'file': filepath, 'method': 'نماشا', 'type': 'video'}
    except Exception as e:
        print(f"خطا در دانلود نماشا: {e}")
    return None

# ================= دانلود پینترست =================
def download_pinterest_image(url):
    try:
        pin_id = re.search(r'/pin/(\d+)/', url)
        if not pin_id:
            pin_id = re.search(r'pin\.it/([a-zA-Z0-9]+)', url)
            if pin_id:
                response = requests.head(url, allow_redirects=True, timeout=10)
                url = response.url
                pin_id = re.search(r'/pin/(\d+)/', url)
        
        if pin_id:
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id.group(1)}"
            headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
            response = requests.get(api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    images = data['data'][0].get('images', {})
                    img_url = None
                    for quality in ['orig', '736x', '564x']:
                        if quality in images:
                            img_url = images[quality]['url']
                            break
                    
                    if img_url:
                        unique = str(int(time.time()*1000))
                        response_img = requests.get(img_url, headers=headers, timeout=30)
                        if response_img.status_code == 200:
                            ext = '.jpg'
                            if 'png' in response_img.headers.get('content-type', ''):
                                ext = '.png'
                            filename = os.path.join(DOWNLOAD_PATH, f"pinterest_{unique}{ext}")
                            with open(filename, 'wb') as f:
                                f.write(response_img.content)
                            return {'file': filename, 'method': 'پینترست', 'type': 'image'}
    except Exception as e:
        print(f"خطا در دانلود پینترست: {e}")
    return None

# ================= کلاس دانلودر جهانی =================
class UniversalDownloader:
    def __init__(self):
        self.methods = [
            self.method_youtube,
            self.method_aparat,
            self.method_telewebion,
            self.method_filimo,
            self.method_namasha,
            self.method_pinterest,
            self.method_ytdlp_best,
            self.method_ytdlp_720p,
            self.method_audio,
            self.method_subprocess_best,
            self.method_subprocess_audio,
            self.method_fallback,
        ]
        self.method_names = [
            "یوتیوب ویژه",
            "آپارات ویژه",
            "تلوبیون ویژه",
            "فیلیمو ویژه",
            "نماشا ویژه",
            "پینترست ویژه",
            "بهترین کیفیت",
            "کیفیت 720p",
            "دانلود صوتی",
            "subprocess بهترین",
            "subprocess صوتی",
            "fallback نهایی",
        ]
    
    def method_youtube(self, url):
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return None
        
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"youtube_{unique}.%(ext)s")
        
        clients = ['android_embedded', 'ios', 'web', 'android']
        for client in clients:
            try:
                ydl_opts = {
                    'format': 'best[height<=720]/best',
                    'outtmpl': output,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'retries': 15,
                    'extractor_args': {'youtube': {'player_client': [client]}},
                    'user_agent': random.choice(USER_AGENTS),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if 'requested_downloads' in info:
                        filepath = info['requested_downloads'][0]['filepath']
                    else:
                        filepath = ydl.prepare_filename(info)
                    
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 10240:
                        return {'file': filepath, 'method': f'یوتیوب ({client})', 'type': 'video'}
            except Exception as e:
                print(f"یوتیوب با {client} خطا: {e}")
                continue
        return None
    
    def method_aparat(self, url):
        if 'aparat.com' in url or 'i.aparat.com' in url:
            return download_aparat(url)
        return None
    
    def method_telewebion(self, url):
        if 'telewebion.com' in url:
            return download_telewebion(url)
        return None
    
    def method_filimo(self, url):
        if 'filimo.com' in url or 'filimo.ir' in url:
            return download_filimo(url)
        return None
    
    def method_namasha(self, url):
        if 'namasha.com' in url:
            return download_namasha(url)
        return None
    
    def method_pinterest(self, url):
        if 'pinterest.com' in url or 'pin.it' in url:
            return download_pinterest_image(url)
        return None
    
    def method_ytdlp_best(self, url):
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"best_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 10,
            'user_agent': random.choice(USER_AGENTS),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                    return {'file': filepath, 'method': 'بهترین کیفیت', 'type': 'video'}
        except Exception as e:
            print(f"best error: {e}")
        return None
    
    def method_ytdlp_720p(self, url):
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"720p_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 10,
            'user_agent': random.choice(USER_AGENTS),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                    return {'file': filepath, 'method': 'کیفیت 720p', 'type': 'video'}
        except Exception as e:
            print(f"720p error: {e}")
        return None
    
    def method_audio(self, url):
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            'user_agent': random.choice(USER_AGENTS),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                filepath = os.path.splitext(filepath)[0] + '.mp3'
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                    return {'file': filepath, 'method': 'دانلود صوتی', 'type': 'audio'}
        except Exception as e:
            print(f"audio error: {e}")
        return None
    
    def method_subprocess_best(self, url):
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"sub_best_{unique}.mp4")
        cmd = ['yt-dlp', '-f', 'best', '-o', output, '--no-playlist', '--quiet', url]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 1024:
                return {'file': output, 'method': 'subprocess بهترین', 'type': 'video'}
        except Exception as e:
            print(f"subprocess error: {e}")
        return None
    
    def method_subprocess_audio(self, url):
        unique = str(int(time.time()*1000))
        output = os.path.join(DOWNLOAD_PATH, f"sub_audio_{unique}.mp3")
        cmd = ['yt-dlp', '-f', 'bestaudio', '--extract-audio', '--audio-format', 'mp3', '-o', output, '--no-playlist', '--quiet', url]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 1024:
                return {'file': output, 'method': 'subprocess صوتی', 'type': 'audio'}
        except Exception as e:
            print(f"subprocess audio error: {e}")
        return None
    
    def method_fallback(self, url):
        formats = ['worst', 'worstaudio']
        for fmt in formats:
            try:
                unique = str(int(time.time()*1000))
                output = os.path.join(DOWNLOAD_PATH, f"fallback_{unique}.%(ext)s")
                ydl_opts = {
                    'format': fmt,
                    'outtmpl': output,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'user_agent': random.choice(USER_AGENTS),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filepath = ydl.prepare_filename(info)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                        return {'file': filepath, 'method': 'fallback', 'type': 'video'}
            except Exception as e:
                print(f"fallback error: {e}")
                continue
        return None
    
    def download(self, url, content_type_hint=None, progress_callback=None):
        # لینک مستقیم تصویر
        if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            result = download_image_direct(url)
            if result:
                return result
        
        # اولویت صوتی
        if content_type_hint == 'audio':
            audio_methods = [self.method_audio, self.method_subprocess_audio]
            for method in audio_methods:
                result = method(url)
                if result:
                    return result
        
        # روش‌های اصلی
        for i, method in enumerate(self.methods):
            if progress_callback:
                progress_callback(f"🔄 روش {i+1}: {self.method_names[i]}...")
            try:
                result = method(url)
                if result:
                    return result
            except Exception as e:
                print(f"Method {i+1} error: {e}")
            time.sleep(1)
        return None

downloader = UniversalDownloader()

# ================= دستور استارت =================
@bot.message_handler(commands=['start'])
def start(message):
    if not is_member(message.from_user.id):
        bot.reply_to(message, "🔒 **برای استفاده از ربات ابتدا در کانال عضو شوید.**", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    welcome_text = (
        "🎬 **ربات دانلود جهانی**\n\n"
        "🤖 **تشخیص خودکار:**\n"
        "✅ عکس 📸 | فیلم 🎥 | آهنگ 🎵\n\n"
        "✅ **۱۲ روش مختلف دانلود**\n"
        "✅ یوتیوب | اینستاگرام | تیک‌تاک\n"
        "✅ آپارات | تلوبیون | فیلیمو | نماشا\n"
        "✅ پینترست | توییتر | فیسبوک\n\n"
        "📌 **فقط کافیه لینک رو بفرستی!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# ================= دریافت لینک =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    
    if not is_member(user_id):
        pending_links[user_id] = message.text
        bot.reply_to(message, "🔒 **ابتدا در کانال عضو شوید.**", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    if user_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return
    
    url = extract_url(message.text)
    if not url:
        return
    
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**", parse_mode="Markdown")
        url = resolved_url
    
    platform = detect_platform(url)
    user_links[user_id] = url
    
    bot.send_message(message.chat.id, "🔍 **در حال تشخیص خودکار نوع محتوا...**", parse_mode="Markdown")
    content_type, type_name = detect_content_type(url)
    user_links[user_id + "_type"] = content_type
    
    type_emoji = {'image': '🖼️', 'video': '🎥', 'audio': '🎵'}.get(content_type, '📄')
    type_fa = {'image': 'عکس', 'video': 'ویدیو', 'audio': 'آهنگ'}.get(content_type, 'محتوای دیجیتال')
    
    bot.send_message(message.chat.id, f"{type_emoji} **تشخیص خودکار:** این لینک یک **{type_fa}** است!", parse_mode="Markdown")
    
    bot.reply_to(message, f"📥 **پلتفرم: {platform}**\n\nلطفاً نوع دانلود رو انتخاب کن:", reply_markup=auto_keyboard(content_type), parse_mode="Markdown")

# ================= کالبک =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if call.data == "check_join":
        if is_member(user_id):
            bot.answer_callback_query(call.id, "عضویت تایید شد ✅")
            bot.edit_message_text("✅ عضویت شما تایید شد!", chat_id, call.message.message_id)
            if user_id in pending_links:
                pending_text = pending_links.pop(user_id)
                fake_message = type('obj', (object,), {
                    'from_user': type('obj', (object,), {'id': user_id})(),
                    'chat': type('obj', (object,), {'id': chat_id})(),
                    'text': pending_text
                })()
                handle(fake_message)
        else:
            bot.answer_callback_query(call.id, "هنوز عضو نیستید ❌")
        return
    
    if call.data == "cancel":
        bot.edit_message_text("❌ عملیات لغو شد.", chat_id, call.message.message_id)
        return
    
    if user_id in active_downloads:
        bot.answer_callback_query(call.id, "⏳ صبر کن دانلود قبلی تموم شه!")
        return
    
    url = user_links.get(user_id)
    if not url:
        bot.answer_callback_query(call.id, "❌ خطا: لینک یافت نشد!")
        return
    
    content_type = user_links.get(user_id + "_type", 'video')
    download_type = call.data
    is_audio_only = (download_type == 'audio')
    
    type_name = "ویدیو" if download_type == 'video' else ("آهنگ" if download_type == 'audio' else "تصویر")
    bot.edit_message_text(f"🔄 **در حال دانلود {type_name}...**\n⏳ این فرآیند چند لحظه طول می‌کشد", chat_id, call.message.message_id, parse_mode="Markdown")
    
    def process():
        try:
            with lock:
                active_downloads[user_id] = time.time()
            
            hint = 'audio' if is_audio_only else None
            result = downloader.download(url, hint)
            
            if result and result.get('file') and os.path.exists(result['file']):
                file_size = os.path.getsize(result['file'])
                
                if file_size > MAX_FILE_SIZE:
                    bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f} مگابایت است!")
                    os.remove(result['file'])
                    return
                
                with open(result['file'], 'rb') as f:
                    if result.get('type') == 'image' or result['file'].endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        bot.send_photo(chat_id, f, caption=f"✅ **تصویر دانلود شد!**\n📥 روش: {result['method']}\n📊 حجم: {file_size/1024/1024:.1f}MB", timeout=300)
                    elif result.get('type') == 'audio' or result['file'].endswith('.mp3'):
                        bot.send_audio(chat_id, f, caption=f"✅ **آهنگ دانلود شد!**\n📥 روش: {result['method']}\n📊 حجم: {file_size/1024/1024:.1f}MB", timeout=300)
                    else:
                        bot.send_video(chat_id, f, caption=f"✅ **ویدیو دانلود شد!**\n📥 روش: {result['method']}\n📊 حجم: {file_size/1024/1024:.1f}MB", timeout=300)
                
                os.remove(result['file'])
                bot.edit_message_text("✅ **دانلود با موفقیت انجام شد!**", chat_id, call.message.message_id)
            else:
                bot.send_message(chat_id, "❌ **خطا در دانلود!**\nهمه روش‌ها امتحان شدند اما موفق نبود.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")
        finally:
            with lock:
                if user_id in active_downloads:
                    del active_downloads[user_id]
                if user_id in user_links:
                    del user_links[user_id]
                if user_id + "_type" in user_links:
                    del user_links[user_id + "_type"]
    
    threading.Thread(target=process, daemon=True).start()

# ================= ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    text = f"👑 **پنل مدیریت**\n\n✅ دانلود فعال: {len(active_downloads)}\n✅ کاربران در صف: {len(pending_links)}"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ================= Webhook =================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "ربات دانلود جهانی فعال است!", 200

@app.route("/health", methods=["GET"])
def health():
    return {"status": "healthy", "timestamp": time.time()}, 200

# ================= اجرا =================
if __name__ == "__main__":
    print("="*50)
    print("🎬 ربات دانلود جهانی فعال شد!")
    print("="*50)
    
    # حذف webhook قبلی و تنظیم مجدد
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print(f"✅ پورت: {PORT}")
    print("="*50)
    
    app.run(host="0.0.0.0", port=PORT)
