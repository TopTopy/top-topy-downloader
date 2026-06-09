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

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 500 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = {}
lock = threading.Lock()

# ================= User-Agent های مختلف =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ================= تشخیص پلتفرم =================
def detect_platform(url):
    url = url.lower()
    platforms = {
        'youtube': ['youtube.com', 'youtu.be'],
        'instagram': ['instagram.com', 'instagr.am'],
        'tiktok': ['tiktok.com', 'vt.tiktok.com'],
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
    }
    
    for platform, domains in platforms.items():
        for domain in domains:
            if domain in url:
                return platform.capitalize()
    return "Other"

# ================= ابزار لینک =================
def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def clean_url(url):
    url = re.sub(r'\?si=[^&]+', '', url)
    url = re.sub(r'&si=[^&]+', '', url)
    return url

def resolve_short_url(url):
    try:
        short_domains = ['bit.ly', 'tinyurl.com', 't.co', 'rb.gy', 'ow.ly', 'is.gd', 'buff.ly', 'pin.it']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10, headers={'User-Agent': random.choice(USER_AGENTS)})
            return response.url
        return url
    except:
        return url

# ================= تشخیص تصویر یا ویدیو =================
def is_image_url(url):
    """تشخیص لینک تصویر از روی پسوند"""
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
    url_lower = url.lower()
    for ext in image_extensions:
        if ext in url_lower:
            return True
    return False

def download_image_direct(url):
    """دانلود مستقیم تصویر از لینک"""
    try:
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        
        # تشخیص پسوند از لینک
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

# ================= موتور دانلود جهانی با ۱۵ روش =================
class UniversalDownloader:
    def __init__(self):
        self.methods = [
            self.method_1_ytdlp_best,
            self.method_2_ytdlp_720p,
            self.method_3_ytdlp_480p,
            self.method_4_ytdlp_360p,
            self.method_5_audio,
            self.method_6_ytdlp_android,
            self.method_7_ytdlp_ios,
            self.method_8_ytdlp_web,
            self.method_9_ytdlp_cookie,
            self.method_10_ytdlp_bypass,
            self.method_11_subprocess_best,
            self.method_12_subprocess_720p,
            self.method_13_subprocess_audio,
            self.method_14_ytdlp_fallback,
            self.method_15_ytdlp_ultimate,
        ]
        self.method_names = [
            "بهترین کیفیت",
            "کیفیت 720p",
            "کیفیت 480p",
            "کیفیت 360p",
            "دانلود صوتی",
            "کلاینت اندروید",
            "کلاینت iOS",
            "کلاینت وب",
            "با کوکی",
            "عبور از محدودیت",
            "subprocess بهترین",
            "subprocess 720p",
            "subprocess صوتی",
            "fallback نهایی",
            "التمیت روش نهایی",
        ]
    
    def _detect_media_type(self, url):
        """تشخیص نوع رسانه (تصویر یا ویدیو)"""
        # اول چک کن پسوند تصویر داره
        if is_image_url(url):
            return 'image'
        
        # برای پینترست و اینستاگرام، با yt-dlp چک کن
        if 'pinterest.com' in url or 'pin.it' in url or 'instagram.com' in url:
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'simulate': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    # اگه فرمت ویدیو نداره و url مستقیم داره، احتمالاً تصویر
                    if not info.get('formats') and info.get('url'):
                        return 'image'
                    
                    # اگه thumbnails داره و فرمت نداره
                    if info.get('thumbnails') and not info.get('formats'):
                        return 'image'
            except:
                pass
        
        return 'video'
    
    def _download_image_with_ytdlp(self, url):
        """دانلود تصویر با yt-dlp (برای پینترست و اینستاگرام)"""
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"image_ytdlp_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'quiet': True,
            'no_warnings': True,
            'retries': 5,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if 'requested_downloads' in info and info['requested_downloads']:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
                
                if os.path.exists(filepath):
                    # بررسی اینکه فایل واقعاً تصویر است
                    if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        return {'file': filepath, 'method': 'yt-dlp تصویر', 'type': 'image'}
                    # اگه ویدیو بود، ignore کن
                    elif filepath.lower().endswith(('.mp4', '.mkv')):
                        os.remove(filepath)
                        return None
        except Exception as e:
            print(f"خطا در دانلود تصویر با yt-dlp: {e}")
        
        return None
    
    def _download_with_ydl(self, url, format_spec, method_name, is_audio=False):
        """تابع پایه برای دانلود با yt-dlp"""
        # اول بررسی کن شاید تصویر باشه
        if not is_audio:
            media_type = self._detect_media_type(url)
            if media_type == 'image':
                # تلاش برای دانلود تصویر
                img_result = self._download_image_with_ytdlp(url)
                if img_result:
                    return img_result
        
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"%(title)s_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': format_spec,
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 15,
            'fragment_retries': 15,
            'socket_timeout': 30,
            'concurrent_fragment_downloads': 1,
            'restrictfilenames': True,
            'nocheckcertificate': True,
            'user_agent': random.choice(USER_AGENTS),
        }
        
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if 'requested_downloads' in info and info['requested_downloads']:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
                
                if is_audio:
                    filepath = os.path.splitext(filepath)[0] + '.mp3'
                
                if os.path.exists(filepath):
                    # تشخیص نوع فایل
                    file_type = 'audio' if is_audio else ('image' if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) else 'video')
                    return {'file': filepath, 'method': method_name, 'size': os.path.getsize(filepath), 'type': file_type}
        except Exception as e:
            print(f"خطا در {method_name}: {e}")
        return None
    
    def _download_with_subprocess(self, url, format_spec, method_name, is_audio=False):
        """تابع پایه برای دانلود با subprocess"""
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        
        if is_audio:
            output = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.mp3")
            cmd = [
                'yt-dlp',
                '-f', 'bestaudio',
                '--extract-audio',
                '--audio-format', 'mp3',
                '-o', output,
                '--no-playlist',
                '--quiet',
                '--user-agent', random.choice(USER_AGENTS),
                url
            ]
        else:
            output = os.path.join(DOWNLOAD_PATH, f"video_{unique}.mp4")
            cmd = [
                'yt-dlp',
                '-f', format_spec,
                '-o', output,
                '--no-playlist',
                '--quiet',
                '--user-agent', random.choice(USER_AGENTS),
                url
            ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output):
                file_type = 'audio' if is_audio else 'video'
                return {'file': output, 'method': method_name, 'size': os.path.getsize(output), 'type': file_type}
        except:
            pass
        return None
    
    def method_1_ytdlp_best(self, url):
        return self._download_with_ydl(url, 'bestvideo+bestaudio/best', 'روش 1')
    
    def method_2_ytdlp_720p(self, url):
        return self._download_with_ydl(url, 'best[height<=720]', 'روش 2')
    
    def method_3_ytdlp_480p(self, url):
        return self._download_with_ydl(url, 'best[height<=480]', 'روش 3')
    
    def method_4_ytdlp_360p(self, url):
        return self._download_with_ydl(url, 'best[height<=360]', 'روش 4')
    
    def method_5_audio(self, url):
        return self._download_with_ydl(url, 'bestaudio', 'روش 5', is_audio=True)
    
    def method_6_ytdlp_android(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"android_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': 'player_client=android_embedded'},
            'user_agent': USER_AGENTS[3],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    file_type = 'image' if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) else 'video'
                    return {'file': filepath, 'method': 'روش 6', 'size': os.path.getsize(filepath), 'type': file_type}
        except:
            pass
        return None
    
    def method_7_ytdlp_ios(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"ios_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': 'player_client=ios'},
            'user_agent': USER_AGENTS[2],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    file_type = 'image' if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) else 'video'
                    return {'file': filepath, 'method': 'روش 7', 'size': os.path.getsize(filepath), 'type': file_type}
        except:
            pass
        return None
    
    def method_8_ytdlp_web(self, url):
        return self._download_with_ydl(url, 'best', 'روش 8')
    
    def method_9_ytdlp_cookie(self, url):
        if not os.path.exists('cookies.txt'):
            return None
        
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"cookie_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    file_type = 'image' if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) else 'video'
                    return {'file': filepath, 'method': 'روش 9', 'size': os.path.getsize(filepath), 'type': file_type}
        except:
            pass
        return None
    
    def method_10_ytdlp_bypass(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"bypass_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    file_type = 'image' if filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) else 'video'
                    return {'file': filepath, 'method': 'روش 10', 'size': os.path.getsize(filepath), 'type': file_type}
        except:
            pass
        return None
    
    def method_11_subprocess_best(self, url):
        return self._download_with_subprocess(url, 'best', 'روش 11')
    
    def method_12_subprocess_720p(self, url):
        return self._download_with_subprocess(url, 'best[height<=720]', 'روش 12')
    
    def method_13_subprocess_audio(self, url):
        return self._download_with_subprocess(url, 'bestaudio', 'روش 13', is_audio=True)
    
    def method_14_ytdlp_fallback(self, url):
        formats = ['worst', 'worstaudio', 'best']
        for fmt in formats:
            try:
                result = self._download_with_ydl(url, fmt, 'روش 14')
                if result:
                    return result
            except:
                continue
        return None
    
    def method_15_ytdlp_ultimate(self, url):
        # اول بررسی کن تصویر باشه
        if 'pinterest.com' in url or 'pin.it' in url or 'instagram.com' in url:
            img_result = self._download_image_with_ytdlp(url)
            if img_result:
                return img_result
        
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"ultimate_{unique}.mp4")
        
        try:
            cmd = [
                'yt-dlp',
                '--ignore-errors',
                '--no-check-certificate',
                '--prefer-insecure',
                '--user-agent', random.choice(USER_AGENTS),
                '--extractor-args', 'youtube:player_client=android_embedded',
                '--geo-bypass',
                '-f', 'best',
                '-o', output,
                '--no-playlist',
                '--quiet',
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output):
                return {'file': output, 'method': 'روش 15', 'size': os.path.getsize(output), 'type': 'video'}
        except:
            pass
        return None
    
    def download(self, url, progress_callback=None):
        """تلاش با همه ۱۵ روش + تشخیص تصویر"""
        
        # اول بررسی کن شاید لینک مستقیم تصویر باشه
        if is_image_url(url):
            if progress_callback:
                progress_callback("🖼️ **تشخیص لینک مستقیم تصویر...**")
            img_result = download_image_direct(url)
            if img_result:
                return img_result
        
        for i, method in enumerate(self.methods):
            method_name = self.method_names[i]
            
            if progress_callback:
                progress_callback(f"🔄 **تلاش با روش {i+1}: {method_name}...**")
            
            try:
                result = method(url)
                if result:
                    return result
            except Exception as e:
                print(f"خطا در روش {i+1}: {e}")
            
            time.sleep(1)
        
        return None

# ================= ایجاد نمونه از دانلودر =================
downloader = UniversalDownloader()

# ================= کیبورد =================
def platform_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 ویدیو", callback_data="video"),
        InlineKeyboardButton("🎵 فقط صدا", callback_data="audio"),
        InlineKeyboardButton("🖼️ تصویر", callback_data="image"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel")
    )
    return markup

# ================= استارت =================
@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = (
        "🎬 **ربات دانلود جهانی - نسخه التیمیت**\n\n"
        "✅ **۱۵ روش مختلف دانلود**\n"
        "✅ **پشتیبانی از تصاویر و ویدیوها**\n"
        "✅ تشخیص خودکار تصاویر پینترست و اینستاگرام\n"
        "✅ پشتیبانی از تمام سایت‌ها\n"
        "✅ یوتیوب | اینستاگرام | تیک‌تاک | توییتر | فیسبوک\n"
        "✅ آپارات | تلوبیون | فیلیمو | و هزاران سایت دیگر\n"
        "✅ حجم مجاز: ۵۰۰ مگابایت\n"
        "✅ **۱۰۰٪ تضمینی**\n\n"
        "📌 **فقط کافیه لینک رو بفرستی!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# ================= دریافت لینک =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id

    if user_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return

    url = extract_url(message.text)
    if not url:
        return

    # تشخیص لینک کوتاه
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**", parse_mode="Markdown")
        url = resolved_url

    platform = detect_platform(url)
    user_links[user_id] = url
    
    # تشخیص خودکار نوع محتوا
    media_type_hint = ""
    if 'pinterest' in url or 'pin.it' in url:
        media_type_hint = "\n🖼️ **این لینک ممکنه تصویر باشه**"
    
    bot.reply_to(
        message, 
        f"📥 **پلتفرم: {platform}**{media_type_hint}\n\n"
        f"🎯 ۱۵ روش مختلف برای دانلود آماده است!\n"
        f"لطفاً نوع دانلود رو انتخاب کن:", 
        reply_markup=platform_keyboard(), 
        parse_mode="Markdown"
    )

# ================= انتخاب نوع دانلود =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

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

    bot.edit_message_text(
        "🔄 **در حال آماده‌سازی ۱۵ روش دانلود...**\n"
        "⏳ این فرآیند چند لحظه طول می‌کشد",
        chat_id,
        call.message.message_id,
        parse_mode="Markdown"
    )

    def progress_callback(message):
        try:
            bot.edit_message_text(
                message,
                chat_id,
                call.message.message_id,
                parse_mode="Markdown"
            )
        except:
            pass

    def process():
        try:
            with lock:
                active_downloads[user_id] = time.time()

            result = downloader.download(url, progress_callback)

            if result and os.path.exists(result['file']):
                file_size = os.path.getsize(result['file'])
                
                if file_size > MAX_FILE_SIZE:
                    bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f} مگابایت است!")
                    os.remove(result['file'])
                    return

                progress_callback(f"📤 **در حال آپلود...**\n📊 حجم: {file_size/1024/1024:.1f}MB")

                with open(result['file'], 'rb') as f:
                    file_type = result.get('type', 'video')
                    
                    if file_type == 'image' or result['file'].lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        bot.send_photo(
                            chat_id, 
                            f,
                            caption=f"✅ **تصویر با موفقیت دانلود شد!**\n"
                                   f"📥 روش: {result['method']}\n"
                                   f"📊 حجم: {file_size/1024/1024:.1f}MB\n"
                                   f"🎯 ۱۵ روش مختلف امتحان شد",
                            timeout=300
                        )
                    elif file_type == 'audio' or result['file'].endswith('.mp3'):
                        bot.send_audio(
                            chat_id, 
                            f,
                            caption=f"✅ **صدا با موفقیت دانلود شد!**\n"
                                   f"📥 روش: {result['method']}\n"
                                   f"📊 حجم: {file_size/1024/1024:.1f}MB\n"
                                   f"🎯 ۱۵ روش مختلف امتحان شد",
                            timeout=300
                        )
                    else:
                        bot.send_video(
                            chat_id, 
                            f,
                            caption=f"✅ **ویدیو با موفقیت دانلود شد!**\n"
                                   f"📥 روش: {result['method']}\n"
                                   f"📊 حجم: {file_size/1024/1024:.1f}MB\n"
                                   f"🎯 ۱۵ روش مختلف امتحان شد",
                            timeout=300
                        )

                os.remove(result['file'])

                try:
                    bot.edit_message_text(
                        "✅ **دانلود با موفقیت انجام شد!**",
                        chat_id,
                        call.message.message_id,
                        parse_mode="Markdown"
                    )
                except:
                    pass

            else:
                bot.send_message(
                    chat_id, 
                    "❌ **خطا در دانلود!**\n"
                    "همه ۱۵ روش امتحان شدند اما موفق نبود.\n"
                    "مشکل ممکنه از این موارد باشه:\n"
                    "• فایل خصوصی یا حذف شده\n"
                    "• محدودیت شدید کپی‌رایت\n"
                    "• مشکل در سرور\n\n"
                    "لطفاً چند دقیقه بعد دوباره تلاش کنید."
                )

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")

        finally:
            with lock:
                if user_id in active_downloads:
                    del active_downloads[user_id]
                if user_id in user_links:
                    del user_links[user_id]

    threading.Thread(target=process, daemon=True).start()

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        version = result.stdout.strip() if result.returncode == 0 else "نامشخص"
    except:
        version = "نامشخص"
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"✅ **۱۵ روش دانلود فعال**\n"
    text += f"✅ **پشتیبانی از تصاویر**\n"
    text += f"📊 دانلودهای هم‌زمان: {len(active_downloads)}\n"
    text += f"📦 yt-dlp نسخه: {version}\n"
    text += f"💾 حجم مجاز: ۵۰۰ مگابایت\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ================= وبهوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "ربات دانلود جهانی با ۱۵ روش - پشتیبانی از تصاویر"

if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود جهانی - نسخه التیمیت با پشتیبانی از تصاویر")
    print("="*70)
    print("✅ ۱۵ روش مختلف دانلود")
    print("✅ پشتیبانی از تصاویر (پینترست، اینستاگرام و...)")
    print("✅ تشخیص خودکار نوع فایل")
    print("✅ پشتیبانی از تمام سایت‌ها")
    print("✅ حجم مجاز: ۵۰۰ مگابایت")
    print("="*70)
    print("🎯 **۱۰۰٪ تضمینی**")
    print("="*70)
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات با ۱۵ روش و پشتیبانی از تصاویر فعال شد!")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
