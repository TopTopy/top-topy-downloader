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

# ================= سیستم دانلود فوق پیشرفته با ۶ روش برای هر پلتفرم =================
class AdvancedDownloader:
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
        
        # اضافه کردن کوکی‌های پیشفرض
        self.session.cookies.update({
            'CONSENT': 'YES+',
            'VISITOR_INFO1_LIVE': 'ST1TFB5k0cU',
        })
        
    def get_with_retry(self, url, max_retries=5, timeout=30):
        """دریافت با چندین بار تلاش و User-Agent مختلف"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        
        for attempt in range(max_retries):
            try:
                # تغییر User-Agent هر بار
                self.session.headers.update({"User-Agent": random.choice(user_agents)})
                
                response = self.session.get(
                    url, 
                    timeout=timeout,
                    allow_redirects=True,
                    verify=False
                )
                
                if response.status_code == 200:
                    return response
                elif response.status_code in [403, 429, 500, 502, 503]:
                    wait_time = 2 ** attempt + random.random()
                    time.sleep(wait_time)
                    
            except Exception as e:
                print(f"تلاش {attempt + 1} ناموفق: {e}")
                time.sleep(1)
        
        return None

# ================= موتور دانلود اصلی =================
class UniversalDownloadEngine:
    def __init__(self):
        self.downloader = AdvancedDownloader()
        
    def _download_file(self, url, prefix):
        """دانلود فایل از لینک مستقیم"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.google.com/",
            }
            
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            
            if response.status_code == 200:
                # تشخیص پسوند فایل
                content_type = response.headers.get('content-type', '')
                if 'video' in content_type:
                    ext = '.mp4'
                elif 'image' in content_type:
                    ext = '.jpg'
                elif 'audio' in content_type:
                    ext = '.mp3'
                else:
                    # استخراج از URL
                    ext = os.path.splitext(url.split('?')[0])[1]
                    if not ext:
                        ext = '.mp4'
                
                filename = f"{DOWNLOAD_PATH}/{prefix}_{int(time.time())}{ext}"
                
                # دانلود با نمایش پیشرفت
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                
                return {
                    'filename': filename,
                    'size': downloaded,
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
                            'type': 'ytdlp',
                            'info': info
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
                    'type': 'ytdlp',
                    'info': info
                }
                
        except Exception as e:
            print(f"خطا در پیدا کردن فایل: {e}")
            return None

    # ========== روش‌های یوتیوب (۶ روش) ==========
    def youtube_method_1_ytdlp_advanced(self, url):
        """روش 1: yt-dlp با تنظیمات فوق پیشرفته"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
                'extract_flat': False,
                'force_generic_extractor': False,
                'nocheckcertificate': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': f'{DOWNLOAD_PATH}/youtube_%(title)s_%(id)s.%(ext)s',
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
    
    def youtube_method_2_api_cobalt(self, url):
        """روش 2: استفاده از API cobalt.tools"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {
                "url": url,
                "downloadMode": "auto",
                "videoQuality": "max",
                "audioFormat": "best",
                "isAudioOnly": False,
            }
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "youtube_cobalt")
        except:
            return None
    
    def youtube_method_3_api_rapid(self, url):
        """روش 3: استفاده از RapidAPI (Savetube)"""
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
    
    def youtube_method_4_api_yt1s(self, url):
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
    
    def youtube_method_5_audio_only(self, url):
        """روش 5: دانلود فقط صدا"""
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
    
    def youtube_method_6_720p_fallback(self, url):
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
    
    # ========== روش‌های اینستاگرام (۶ روش) ==========
    def instagram_method_1_api_cobalt(self, url):
        """روش 1: API cobalt.tools برای اینستاگرام"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {"url": url, "downloadMode": "auto"}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "instagram_cobalt")
        except:
            return None
    
    def instagram_method_2_saveinsta(self, url):
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
                    import re
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "instagram_saveinsta")
        except:
            return None
    
    def instagram_method_3_igdownloader(self, url):
        """روش 3: استفاده از IGDownloader"""
        try:
            api_url = "https://igdownloader.app/api/ajaxSearch"
            data = {"q": url, "t": "media"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    import re
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "instagram_igdownloader")
        except:
            return None
    
    def instagram_method_4_snapinsta(self, url):
        """روش 4: استفاده از SnapInsta"""
        try:
            api_url = "https://snapinsta.app/api/ajaxSearch"
            data = {"q": url, "t": "media"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    import re
                    urls = re.findall(r'href="([^"]+\.(mp4|jpg|png))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "instagram_snapinsta")
        except:
            return None
    
    def instagram_method_5_ytdlp(self, url):
        """روش 5: yt-dlp برای اینستاگرام"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
                'outtmpl': f'{DOWNLOAD_PATH}/instagram_%(title)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    def instagram_method_6_direct_extract(self, url):
        """روش 6: استخراج مستقیم از HTML صفحه"""
        try:
            response = self.downloader.get_with_retry(url)
            if response:
                patterns = [
                    r'<meta property="og:video" content="([^"]+)"',
                    r'<meta property="og:image" content="([^"]+)"',
                    r'"video_url":"([^"]+)"',
                    r'"display_url":"([^"]+)"',
                    r'"src":"([^"]+\.mp4)"',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, response.text)
                    for media_url in matches:
                        media_url = media_url.replace('\\u0026', '&')
                        if media_url.startswith('//'):
                            media_url = 'https:' + media_url
                        
                        result = self._download_file(media_url, "instagram_direct")
                        if result:
                            return result
        except:
            return None
    
    # ========== روش‌های پینترست (۶ روش) ==========
    def pinterest_method_1_api_official(self, url):
        """روش 1: API رسمی پینترست"""
        try:
            # استخراج ID پین
            pin_id = None
            patterns = [r'/pin/(\d+)', r'pin_id=(\d+)']
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    pin_id = match.group(1)
                    break
            
            if pin_id:
                api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
                response = requests.get(api_url, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data") and data["data"][0].get("images"):
                        images = data["data"][0]["images"]
                        img_url = images.get("orig", {}).get("url") or images.get("736x", {}).get("url")
                        
                        if img_url:
                            return self._download_file(img_url, "pinterest_api")
        except:
            return None
    
    def pinterest_method_2_pindown(self, url):
        """روش 2: استفاده از PinDown.app"""
        try:
            api_url = "https://pindown.app/api/download"
            data = {"url": url}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("download_url"):
                    return self._download_file(data["download_url"], "pinterest_pindown")
        except:
            return None
    
    def pinterest_method_3_savepin(self, url):
        """روش 3: استفاده از SavePin.io"""
        try:
            api_url = "https://savepin.io/fetch"
            data = {"url": url}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                import re
                urls = re.findall(r'href="([^"]+\.(jpg|png|mp4))"', response.text)
                for url_match in urls:
                    download_url = url_match[0]
                    if download_url:
                        return self._download_file(download_url, "pinterest_savepin")
        except:
            return None
    
    def pinterest_method_4_pinvideo(self, url):
        """روش 4: استفاده از PinVideo.io"""
        try:
            api_url = "https://pinvideo.io/api/fetch"
            data = {"url": url}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("url"):
                    return self._download_file(data["url"], "pinterest_pinvideo")
        except:
            return None
    
    def pinterest_method_5_ytdlp(self, url):
        """روش 5: yt-dlp برای پینترست"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
                'outtmpl': f'{DOWNLOAD_PATH}/pinterest_%(title)s.%(ext)s',
                'force_generic_extractor': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    def pinterest_method_6_direct_extract(self, url):
        """روش 6: استخراج مستقیم از HTML"""
        try:
            response = self.downloader.get_with_retry(url)
            if response:
                patterns = [
                    r'<meta property="og:image" content="([^"]+)"',
                    r'<meta property="og:video" content="([^"]+)"',
                    r'"image":"([^"]+pinimg[^"]+)"',
                    r'"image_original_url":"([^"]+)"',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, response.text)
                    for media_url in matches:
                        if media_url:
                            media_url = media_url.replace('\\u002F', '/')
                            return self._download_file(media_url, "pinterest_direct")
        except:
            return None
    
    # ========== روش‌های تیک‌تاک (۶ روش) ==========
    def tiktok_method_1_api_cobalt(self, url):
        """روش 1: API cobalt.tools برای تیک‌تاک"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {"url": url, "downloadMode": "auto"}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "tiktok_cobalt")
        except:
            return None
    
    def tiktok_method_2_tikwm(self, url):
        """روش 2: استفاده از TikWM.com"""
        try:
            api_url = "https://tikwm.com/api/"
            data = {"url": url, "hd": 1}
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            response = requests.post(api_url, data=data, headers=headers, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("data"):
                    download_url = result["data"].get("play") or result["data"].get("hdplay")
                    if download_url:
                        return self._download_file(download_url, "tiktok_tikwm")
        except:
            return None
    
    def tiktok_method_3_snaptik(self, url):
        """روش 3: استفاده از SnapTik.app"""
        try:
            api_url = "https://snaptik.app/api/ajaxSearch"
            data = {"q": url, "lang": "en"}
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            
            response = requests.post(api_url, data=data, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    import re
                    urls = re.findall(r'href="([^"]+\.mp4)"', data["data"])
                    for download_url in urls:
                        if download_url:
                            return self._download_file(download_url, "tiktok_snaptik")
        except:
            return None
    
    def tiktok_method_4_ssstik(self, url):
        """روش 4: استفاده از SSSTik.io"""
        try:
            api_url = "https://ssstik.io/api"
            data = {"url": url}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("url"):
                    return self._download_file(data["url"], "tiktok_ssstik")
        except:
            return None
    
    def tiktok_method_5_musicaldown(self, url):
        """روش 5: استفاده از MusicalDown.com"""
        try:
            api_url = "https://musicaldown.com/api/download"
            data = {"url": url}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("video_url"):
                    return self._download_file(data["video_url"], "tiktok_musicaldown")
        except:
            return None
    
    def tiktok_method_6_ytdlp(self, url):
        """روش 6: yt-dlp برای تیک‌تاک"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best',
                'outtmpl': f'{DOWNLOAD_PATH}/tiktok_%(title)s.%(ext)s',
                'extractor_args': {'tiktok': {'app_version': 'latest'}}
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    # ========== روش‌های عمومی (۶ روش) ==========
    def general_method_1_ytdlp(self, url):
        """روش 1: yt-dlp برای سایت‌های عمومی"""
        try:
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            ]
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[filesize<300M]/best',
                'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
                'socket_timeout': 30,
                'retries': 5,
                'http_headers': {
                    'User-Agent': random.choice(user_agents),
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    return self._get_downloaded_file(info)
        except:
            return None
    
    def general_method_2_direct_request(self, url):
        """روش 2: دانلود مستقیم با requests"""
        try:
            response = self.downloader.get_with_retry(url, max_retries=3)
            if response and 'content-type' in response.headers:
                content_type = response.headers['content-type']
                
                if any(x in content_type for x in ['video', 'image', 'audio']):
                    filename = f"{DOWNLOAD_PATH}/direct_{int(time.time())}"
                    
                    if 'video' in content_type:
                        filename += '.mp4'
                    elif 'image' in content_type:
                        filename += '.jpg'
                    elif 'audio' in content_type:
                        filename += '.mp3'
                    else:
                        filename += '.bin'
                    
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    
                    return {
                        'filename': filename,
                        'size': len(response.content),
                        'type': 'direct'
                    }
        except:
            return None
    
    def general_method_3_snapsave(self, url):
        """روش 3: استفاده از SnapSave.app برای سایت‌های مختلف"""
        try:
            api_url = "https://snapsave.app/api/ajaxSearch"
            data = {"q": url, "lang": "en"}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    import re
                    urls = re.findall(r'href="([^"]+\.(mp4|mp3|jpg))"', data["data"])
                    for url_match in urls:
                        download_url = url_match[0]
                        if download_url:
                            return self._download_file(download_url, "general_snapsave")
        except:
            return None
    
    def general_method_4_savethevideo(self, url):
        """روش 4: استفاده از SaveTheVideo.com"""
        try:
            api_url = "https://savethevideo.com/api/fetch"
            data = {"url": url}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("download_url"):
                    return self._download_file(data["download_url"], "general_savethevideo")
        except:
            return None
    
    def general_method_5_cobalt(self, url):
        """روش 5: استفاده از cobalt.tools برای سایت‌های عمومی"""
        try:
            api_url = "https://api.cobalt.tools/api/json"
            data = {"url": url, "downloadMode": "auto"}
            
            response = requests.post(api_url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success" and result.get("url"):
                    return self._download_file(result["url"], "general_cobalt")
        except:
            return None
    
    def general_method_6_savetube(self, url):
        """روش 6: استفاده از SaveTube.app"""
        try:
            api_url = "https://savetube.app/api/download"
            data = {"url": url}
            
            response = requests.post(api_url, data=data, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("download_url"):
                    return self._download_file(data["download_url"], "general_savetube")
        except:
            return None
    
    def download(self, url, chat_id, user_id, is_group=False, msg_id=None, platform_type=None):
        """تابع اصلی دانلود با ۶ روش برای هر پلتفرم"""
        
        # تعریف روش‌های دانلود برای هر پلتفرم
        methods_map = {
            "Youtube": [
                self.youtube_method_1_ytdlp_advanced,
                self.youtube_method_2_api_cobalt,
                self.youtube_method_3_api_rapid,
                self.youtube_method_4_api_yt1s,
                self.youtube_method_5_audio_only,
                self.youtube_method_6_720p_fallback,
            ],
            "Instagram": [
                self.instagram_method_1_api_cobalt,
                self.instagram_method_2_saveinsta,
                self.instagram_method_3_igdownloader,
                self.instagram_method_4_snapinsta,
                self.instagram_method_5_ytdlp,
                self.instagram_method_6_direct_extract,
            ],
            "Pinterest": [
                self.pinterest_method_1_api_official,
                self.pinterest_method_2_pindown,
                self.pinterest_method_3_savepin,
                self.pinterest_method_4_pinvideo,
                self.pinterest_method_5_ytdlp,
                self.pinterest_method_6_direct_extract,
            ],
            "Tiktok": [
                self.tiktok_method_1_api_cobalt,
                self.tiktok_method_2_tikwm,
                self.tiktok_method_3_snaptik,
                self.tiktok_method_4_ssstik,
                self.tiktok_method_5_musicaldown,
                self.tiktok_method_6_ytdlp,
            ],
            "Other": [
                self.general_method_1_ytdlp,
                self.general_method_2_direct_request,
                self.general_method_3_snapsave,
                self.general_method_4_savethevideo,
                self.general_method_5_cobalt,
                self.general_method_6_savetube,
            ]
        }
        
        # انتخاب روش‌های مناسب
        methods = methods_map.get(platform_type, methods_map["Other"])
        platform_name = platform_type if platform_type != "Other" else "عمومی"
        
        # به‌روزرسانی پیام
        if msg_id:
            try:
                bot.edit_message_text(
                    f"🔄 **در حال دانلود از {platform_name}...**\n📡 {len(methods)} روش مختلف آماده شد",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        
        # امتحان همه روش‌ها
        for i, method in enumerate(methods, 1):
            try:
                if msg_id:
                    try:
                        bot.edit_message_text(
                            f"🔄 **{platform_name}** - روش {i}/{len(methods)}...",
                            chat_id,
                            msg_id,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                result = method(url)
                
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
                            bot.send_video(chat_id, f, caption=f"✅ **دانلود از {platform_name}**")
                        elif result['filename'].endswith(('.mp3', '.m4a', '.ogg')):
                            bot.send_audio(chat_id, f, caption=f"✅ **دانلود از {platform_name}**")
                        elif result['filename'].endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            bot.send_photo(chat_id, f, caption=f"✅ **دانلود از {platform_name}**")
                        else:
                            bot.send_document(chat_id, f, caption=f"✅ **دانلود از {platform_name}**")
                    
                    # ثبت در دیتابیس
                    db.add_download(
                        user_id, chat_id, url,
                        result['type'], result['size'],
                        "group" if is_group else "private",
                        platform_name
                    )
                    
                    # پاک کردن فایل
                    os.remove(result['filename'])
                    
                    if msg_id:
                        try:
                            bot.edit_message_text(
                                f"✅ **دانلود از {platform_name} با موفقیت انجام شد!**",
                                chat_id,
                                msg_id,
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                    
                    return True
                    
            except Exception as e:
                print(f"خطا در روش {i} {platform_name}: {e}")
                continue
        
        # اگر هیچ روشی جواب نداد
        if msg_id:
            try:
                bot.edit_message_text(
                    f"❌ **متأسفانه دانلود از {platform_name} با مشکل مواجه شد**\n\n"
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

# ================= ایجاد نمونه از موتور دانلود =================
downloader_engine = UniversalDownloadEngine()

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

# ================= تابع دانلود اصلی (نسخه فوق العاده قدرتمند) =================
def download_media(url, chat_id, user_id, is_group=False):
    try:
        platform = detect_platform(url)
        
        # ارسال پیام شروع
        msg = bot.send_message(
            chat_id, 
            f"🎯 **پلتفرم: {platform}**\n🔄 **فعال‌سازی موتور دانلود فوق پیشرفته با ۶ روش...**", 
            parse_mode="Markdown"
        )
        
        # استفاده از موتور دانلود پیشرفته
        return downloader_engine.download(url, chat_id, user_id, is_group, msg.message_id, platform)
        
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
        "✅ **فرمت‌ها:** ویدیو، صدا، عکس، GIF\n"
        "✅ **کیفیت:** بالاترین کیفیت موجود\n"
        "✅ **۶ روش دانلود برای هر پلتفرم**\n\n"
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
    
    bot.reply_to(message, "✅ **لینک دریافت شد، شروع دانلود با موتور فوق پیشرفته...**", parse_mode="Markdown")
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
    print("="*70)
    print("🚀 راه‌اندازی ربات قدرتمند دانلود نسخه فوق پیشرفته با ۶ روش برای هر پلتفرم...")
    print("="*70)
    print(f"👤 آیدی ادمین: {ADMIN_ID}")
    print(f"📁 مسیر دانلود: {DOWNLOAD_PATH}")
    print(f"📊 حجم مجاز: {MAX_FILE_SIZE/1024/1024}MB")
    print("✅ یوتیوب: ۶ روش دانلود (yt-dlp پیشرفته، cobalt.tools، RapidAPI، yt1s، صوتی، 720p)")
    print("✅ اینستاگرام: ۶ روش دانلود (cobalt.tools، SaveInsta، IGDownloader، SnapInsta، yt-dlp، استخراج مستقیم)")
    print("✅ پینترست: ۶ روش دانلود (API رسمی، PinDown، SavePin، PinVideo، yt-dlp، استخراج مستقیم)")
    print("✅ تیک‌تاک: ۶ روش دانلود (cobalt.tools، TikWM، SnapTik، SSSTik، MusicalDown، yt-dlp)")
    print("✅ سایر سایت‌ها: ۶ روش دانلود (yt-dlp، دانلود مستقیم، SnapSave، SaveTheVideo، cobalt.tools، SaveTube)")
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
    print("✅ پشتیبانی از تمام سایت‌ها با ۶ روش مختلف فعال شد")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
