# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import json
import subprocess
import random
import logging
import signal
import hashlib
import shutil
import tempfile
from datetime import datetime
from collections import deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError as FutureTimeoutError
from functools import wraps
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse

# ================= تنظیمات لاگینگ =================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    level=getattr(logging, LOG_LEVEL),
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# ================= تنظیمات =================
TOKEN = os.getenv("BOT_TOKEN", "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8226091292"))
MAX_FILE_SIZE = 180 * 1024 * 1024  # 180MB (کاهش برای اطمینان)
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://web-production-d8a05.up.railway.app/webhook")
PORT = int(os.getenv("PORT", 8080))
REQUIRED_CHANNEL = "@top_topy_downloader"
CHANNEL_LINK = "https://t.me/top_topy_downloader"

# محدودیت‌ها
MAX_DOWNLOADS_PER_MINUTE = 3
MAX_WORKERS = 2  # کاهش به 2 برای جلوگیری از OOM
MAX_QUEUE_SIZE = 20
DOWNLOAD_TIMEOUT = 300
CACHE_TTL = 30  # 30 ثانیه برای کش عضویت
MEMBERSHIP_TTL = 30  # کش عضویت کوتاه‌تر
MAX_CACHE_SIZE = 1000
CLEANUP_INTERVAL = 3600
MAX_USER_RATE_LIMIT_AGE = 86400  # 24 ساعت

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= Session با Retry =================
def create_session_with_retry(retries=3, backoff_factor=0.5):
    """ایجاد session با قابلیت retry خودکار"""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session_with_retry = create_session_with_retry()

# ================= کش حافظه با LRU و TTL =================
class LRUCache:
    def __init__(self, max_size=MAX_CACHE_SIZE, ttl=CACHE_TTL):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.lock = threading.RLock()
    
    def get(self, key):
        with self.lock:
            if key not in self.cache:
                return None
            value, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return value
    
    def set(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = (value, time.time())
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)
    
    def delete(self, key):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
    
    def clear_expired(self):
        with self.lock:
            now = time.time()
            expired = [k for k, (_, t) in self.cache.items() if now - t > self.ttl]
            for k in expired:
                del self.cache[k]
            logger.debug(f"Cleared {len(expired)} expired cache entries")

# ================= مدیریت دانلود با قابلیت لغو واقعی =================
class CancellableDownload:
    def __init__(self):
        self.cancelled = False
        self.process = None
        self.lock = threading.RLock()
    
    def cancel(self):
        with self.lock:
            self.cancelled = True
            if self.process:
                try:
                    self.process.terminate()
                    logger.info("Process terminated by user")
                except:
                    pass
    
    def is_cancelled(self):
        with self.lock:
            return self.cancelled
    
    def set_process(self, process):
        with self.lock:
            self.process = process

class DownloadManager:
    def __init__(self):
        self.active_downloads = {}
        self.lock = threading.RLock()
    
    def register_download(self, user_id):
        with self.lock:
            cancellable = CancellableDownload()
            self.active_downloads[user_id] = cancellable
            return cancellable
    
    def cancel_download(self, user_id):
        with self.lock:
            if user_id in self.active_downloads:
                self.active_downloads[user_id].cancel()
                del self.active_downloads[user_id]
                logger.info(f"Cancelled download for user {user_id}")
                return True
        return False
    
    def is_active(self, user_id):
        with self.lock:
            return user_id in self.active_downloads
    
    def remove_download(self, user_id):
        with self.lock:
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]

# ================= مدیریت صف واقعی با قفل کامل =================
class DownloadQueue:
    def __init__(self, max_size=MAX_QUEUE_SIZE, max_workers=MAX_WORKERS):
        self.queue = deque()
        self.max_size = max_size
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.futures = {}
        self.futures_lock = threading.RLock()
        self.queue_lock = threading.RLock()
        self.user_rate_limit = {}
        self.user_requests = {}
        self.stats_lock = threading.RLock()
        self.download_manager = DownloadManager()
        self.membership_cache = LRUCache(max_size=MAX_CACHE_SIZE, ttl=MEMBERSHIP_TTL)
        self.url_cache = LRUCache(max_size=500, ttl=3600)
        self.processing = False
    
    def add_to_queue(self, user_id, chat_id, url, content_type, is_audio_only, msg_id, request_id):
        with self.queue_lock:
            if len(self.queue) >= self.max_size:
                return False, self.max_size - len(self.queue)
            
            task = {
                'user_id': user_id,
                'chat_id': chat_id,
                'url': url,
                'content_type': content_type,
                'is_audio_only': is_audio_only,
                'msg_id': msg_id,
                'request_id': request_id,
                'added_at': time.time()
            }
            self.queue.append(task)
            logger.info(f"Task added to queue for user {user_id}. Queue size: {len(self.queue)}")
            return True, len(self.queue) - 1
    
    def process_queue(self):
        task = None
        with self.queue_lock:
            if self.queue and len(self.futures) < MAX_WORKERS:
                task = self.queue.popleft()
                logger.info(f"Processing task from queue for user {task['user_id']}. Remaining: {len(self.queue)}")
        
        if task:
            with self.stats_lock:
                self.user_requests[task['request_id']] = task
            
            future = self.executor.submit(
                process_download_task_with_cleanup,
                task['user_id'],
                task['chat_id'],
                task['url'],
                task['content_type'],
                task['is_audio_only'],
                task['msg_id'],
                task['request_id']
            )
            
            with self.futures_lock:
                self.futures[task['request_id']] = {
                    'future': future,
                    'start_time': time.time(),
                    'user_id': task['user_id'],
                    'task': task
                }
            
            future.add_done_callback(lambda f, rid=task['request_id']: self.cleanup_future(rid))
    
    def cleanup_future(self, request_id):
        with self.futures_lock:
            if request_id in self.futures:
                data = self.futures[request_id]
                self.download_manager.remove_download(data['user_id'])
                del self.futures[request_id]
                logger.debug(f"Cleaned up future for request {request_id}")
        
        with self.stats_lock:
            if request_id in self.user_requests:
                del self.user_requests[request_id]
    
    def check_timeouts(self):
        to_cancel = []
        with self.futures_lock:
            now = time.time()
            for request_id, data in self.futures.items():
                if now - data['start_time'] > DOWNLOAD_TIMEOUT:
                    to_cancel.append((request_id, data))
        
        for request_id, data in to_cancel:
            self.download_manager.cancel_download(data['user_id'])
            future = data['future']
            if not future.done():
                future.cancel()
            
            logger.warning(f"Download timeout for user {data['user_id']}")
            try:
                bot.send_message(data['task']['chat_id'], "⏰ **زمان دانلود به اتمام رسید!**\nلطفاً دوباره تلاش کنید.", parse_mode="Markdown")
            except:
                pass
            
            with self.futures_lock:
                if request_id in self.futures:
                    del self.futures[request_id]
            with self.stats_lock:
                if request_id in self.user_requests:
                    del self.user_requests[request_id]
    
    def get_queue_info(self):
        with self.queue_lock:
            queue_size = len(self.queue)
        with self.futures_lock:
            active_count = len(self.futures)
        return queue_size, active_count
    
    def is_user_active(self, user_id):
        return self.download_manager.is_active(user_id)
    
    def is_queue_full(self):
        with self.queue_lock:
            return len(self.queue) >= self.max_size
    
    def add_pending_link(self, user_id, link):
        with self.stats_lock:
            self.user_requests[f"pending_{user_id}"] = link
    
    def get_pending_link(self, user_id):
        with self.stats_lock:
            key = f"pending_{user_id}"
            if key in self.user_requests:
                return self.user_requests.pop(key)
        return None
    
    def add_user_request(self, user_id, url, content_type, request_id):
        with self.stats_lock:
            self.user_requests[request_id] = {
                'user_id': user_id,
                'url': url,
                'content_type': content_type,
                'timestamp': time.time()
            }
    
    def get_user_request(self, request_id):
        with self.stats_lock:
            return self.user_requests.get(request_id)
    
    def check_rate_limit(self, user_id):
        with self.stats_lock:
            now = time.time()
            # پاکسازی رکوردهای قدیمی
            if user_id in self.user_rate_limit:
                while self.user_rate_limit[user_id] and self.user_rate_limit[user_id][0] < now - 60:
                    self.user_rate_limit[user_id].popleft()
            
            if user_id not in self.user_rate_limit:
                self.user_rate_limit[user_id] = deque()
            
            if len(self.user_rate_limit[user_id]) >= MAX_DOWNLOADS_PER_MINUTE:
                remaining = 60 - int(now - self.user_rate_limit[user_id][0])
                return False, remaining
            
            self.user_rate_limit[user_id].append(now)
            return True, 0
    
    def cleanup_rate_limits(self):
        """پاکسازی rate limit کاربران غیرفعال"""
        with self.stats_lock:
            now = time.time()
            to_delete = []
            for user_id, requests in self.user_rate_limit.items():
                if requests and now - requests[-1] > MAX_USER_RATE_LIMIT_AGE:
                    to_delete.append(user_id)
            for user_id in to_delete:
                del self.user_rate_limit[user_id]
            if to_delete:
                logger.info(f"Cleaned up {len(to_delete)} inactive rate limits")
    
    def cache_url_info(self, url, info):
        self.url_cache.set(url, info)
    
    def get_cached_url_info(self, url):
        return self.url_cache.get(url)
    
    def invalidate_membership_cache(self, user_id):
        """باطل کردن کش عضویت یک کاربر"""
        self.membership_cache.delete(str(user_id))

# ================= پاکسازی دوره‌ای =================
def periodic_cleanup():
    while True:
        time.sleep(CLEANUP_INTERVAL)
        
        # پاکسازی فایل‌های قدیمی
        try:
            for f in os.listdir(DOWNLOAD_PATH):
                fpath = os.path.join(DOWNLOAD_PATH, f)
                if os.path.isfile(fpath) and time.time() - os.path.getmtime(fpath) > 3600:
                    os.remove(fpath)
                    logger.info(f"Cleaned up old file: {f}")
        except Exception as e:
            logger.error(f"File cleanup error: {e}")
        
        # پاکسازی کش
        download_queue.membership_cache.clear_expired()
        download_queue.url_cache.clear_expired()
        download_queue.cleanup_rate_limits()
        
        logger.info("Periodic cleanup completed")

cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
cleanup_thread.start()

download_queue = DownloadQueue()

# ================= تابع پردازش صف =================
def queue_processor_loop():
    while True:
        download_queue.process_queue()
        time.sleep(0.5)

queue_thread = threading.Thread(target=queue_processor_loop, daemon=True)
queue_thread.start()

def timeout_checker_loop():
    while True:
        time.sleep(30)
        download_queue.check_timeouts()

timeout_thread = threading.Thread(target=timeout_checker_loop, daemon=True)
timeout_thread.start()

# ================= User-Agent ها =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# ================= بررسی عضویت در کانال =================
def is_member(user_id):
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL, int(user_id))
        is_member = member.status in ["member", "administrator", "creator"]
        return is_member
    except Exception as e:
        logger.error(f"Membership error for {user_id}: {e}")
        return False

def check_membership_with_cache(user_id):
    cached = download_queue.membership_cache.get(str(user_id))
    if cached is not None:
        return cached
    result = is_member(user_id)
    download_queue.membership_cache.set(str(user_id), result)
    return result

def join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK),
        InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")
    )
    return markup

# ================= تشخیص خودکار نوع محتوا =================
def detect_content_type_cached(url):
    cached = download_queue.get_cached_url_info(f"type_{url}")
    if cached:
        return cached
    result = detect_content_type(url)
    download_queue.cache_url_info(f"type_{url}", result)
    return result

def detect_content_type(url):
    url_lower = url.lower()
    
    image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
    video_exts = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']
    audio_exts = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac']
    
    for ext in image_exts:
        if ext in url_lower:
            return 'image', 'عکس'
    for ext in video_exts:
        if ext in url_lower:
            return 'video', 'ویدیو'
    for ext in audio_exts:
        if ext in url_lower:
            return 'audio', 'آهنگ'
    
    if any(d in url_lower for d in ['instagram.com/p/', 'pinterest.com', 'pin.it']):
        return 'image', 'عکس'
    if any(d in url_lower for d in ['soundcloud.com', 'spotify.com']):
        return 'audio', 'آهنگ'
    
    return 'video', 'ویدیو'

def auto_keyboard(content_type):
    markup = InlineKeyboardMarkup(row_width=2)
    if content_type == 'image':
        markup.add(InlineKeyboardButton("🖼️ دانلود عکس", callback_data="image"))
    elif content_type == 'audio':
        markup.add(InlineKeyboardButton("🎵 دانلود آهنگ", callback_data="audio"))
    else:
        markup.add(
            InlineKeyboardButton("🎥 دانلود ویدیو", callback_data="video"),
            InlineKeyboardButton("🎵 دانلود صدا", callback_data="audio")
        )
    markup.add(InlineKeyboardButton("❌ لغو", callback_data="cancel"))
    return markup

# ================= دانلود با کنترل دقیق حجم =================
def download_file_with_progress(url, headers, filename, max_size=MAX_FILE_SIZE, cancellable=None):
    try:
        head_success = False
        try:
            head_response = session_with_retry.head(url, headers=headers, timeout=30)
            content_length = head_response.headers.get('content-length')
            if content_length:
                file_size = int(content_length)
                if file_size > max_size:
                    return None, file_size
            head_success = True
        except Exception as e:
            logger.debug(f"HEAD request failed, continuing with GET: {e}")
        
        response = session_with_retry.get(url, headers=headers, timeout=60, stream=True)
        response.raise_for_status()
        
        downloaded = 0
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if cancellable and cancellable.is_cancelled():
                    f.close()
                    os.remove(filename)
                    return None, 0
                
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        f.close()
                        os.remove(filename)
                        return None, downloaded
        
        return filename, downloaded
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None, 0

def download_image_direct(url, cancellable=None):
    try:
        unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
        ext = '.jpg'
        for known_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            if known_ext in url.lower():
                ext = known_ext
                break
        
        filename = os.path.join(DOWNLOAD_PATH, f"image_{unique}{ext}")
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        
        result, size = download_file_with_progress(url, headers, filename, MAX_FILE_SIZE, cancellable)
        if result and size > 1024:
            return {'file': filename, 'method': 'دانلود مستقیم', 'type': 'image'}
    except Exception as e:
        logger.error(f"Image download error: {e}")
    return None

# ================= دانلود آپارات =================
def download_aparat(url, cancellable=None):
    try:
        video_id = None
        patterns = [r'aparat\.com/v/([a-zA-Z0-9]+)', r'aparat\.com/([a-zA-Z0-9]+)', r'i\.aparat\.com/([a-zA-Z0-9]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        if video_id:
            api_url = f"https://www.aparat.com/etc/api/video/videoID/{video_id}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = session_with_retry.get(api_url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if 'video' in data and data['video'].get('file'):
                    video_url = data['video']['file']
                    unique = f"{int(time.time()*1000)}"
                    filename = os.path.join(DOWNLOAD_PATH, f"aparat_{unique}.mp4")
                    result, size = download_file_with_progress(video_url, headers, filename, MAX_FILE_SIZE, cancellable)
                    if result:
                        return {'file': filename, 'method': 'آپارات', 'type': 'video'}
    except Exception as e:
        logger.error(f"Aparat error: {e}")
    return None

# ================= دانلود تلوبیون =================
def download_telewebion(url, cancellable=None):
    try:
        program_id = re.search(r'telewebion\.com/program/(\d+)', url)
        if program_id:
            api_url = f"https://www.telewebion.com/api/program/{program_id.group(1)}"
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = session_with_retry.get(api_url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data', {}).get('video_url'):
                    video_url = data['data']['video_url']
                    unique = f"{int(time.time()*1000)}"
                    filename = os.path.join(DOWNLOAD_PATH, f"telewebion_{unique}.mp4")
                    result, size = download_file_with_progress(video_url, headers, filename, MAX_FILE_SIZE, cancellable)
                    if result:
                        return {'file': filename, 'method': 'تلوبیون', 'type': 'video'}
    except Exception as e:
        logger.error(f"Telewebion error: {e}")
    return None

# ================= دانلود فیلیمو =================
def download_filimo(url, cancellable=None):
    try:
        unique = f"{int(time.time()*1000)}"
        output = os.path.join(DOWNLOAD_PATH, f"filimo_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
            'user_agent': random.choice(USER_AGENTS),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                return {'file': filepath, 'method': 'فیلیمو', 'type': 'video'}
    except Exception as e:
        logger.error(f"Filimo error: {e}")
    return None

# ================= دانلود پینترست =================
def download_pinterest_image(url, cancellable=None):
    try:
        pin_id = re.search(r'/pin/(\d+)/', url)
        if not pin_id:
            pin_match = re.search(r'pin\.it/([a-zA-Z0-9]+)', url)
            if pin_match:
                resp = session_with_retry.head(url, allow_redirects=True, timeout=10)
                url = resp.url
                pin_id = re.search(r'/pin/(\d+)/', url)
        
        if pin_id:
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id.group(1)}"
            headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
            resp = session_with_retry.get(api_url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data') and len(data['data']) > 0:
                    images = data['data'][0].get('images', {})
                    img_url = None
                    for quality in ['orig', '736x', '564x']:
                        if quality in images:
                            img_url = images[quality]['url']
                            break
                    if img_url:
                        unique = f"{int(time.time()*1000)}"
                        filename = os.path.join(DOWNLOAD_PATH, f"pinterest_{unique}.jpg")
                        result, size = download_file_with_progress(img_url, headers, filename, MAX_FILE_SIZE, cancellable)
                        if result:
                            return {'file': filename, 'method': 'پینترست', 'type': 'image'}
    except Exception as e:
        logger.error(f"Pinterest error: {e}")
    return None

# ================= کلاس دانلودر با پشتیبانی از Kill =================
class UniversalDownloader:
    def __init__(self):
        self.methods = [
            self.method_youtube,
            self.method_aparat,
            self.method_telewebion,
            self.method_filimo,
            self.method_pinterest,
            self.method_ytdlp,
        ]
        self.method_names = [
            "یوتیوب ویژه",
            "آپارات ویژه",
            "تلوبیون ویژه",
            "فیلیمو ویژه",
            "پینترست ویژه",
            "دانلودر عمومی",
        ]
    
    def method_youtube(self, url, cancellable=None):
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return None
        
        unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
        output = os.path.join(DOWNLOAD_PATH, f"youtube_{unique}.%(ext)s")
        
        clients = ['android_embedded', 'ios', 'web']
        for client in clients:
            if cancellable and cancellable.is_cancelled():
                return None
            
            try:
                ydl_opts = {
                    'format': 'best[height<=720]/best',
                    'outtmpl': output,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'retries': 5,
                    'extractor_args': {'youtube': {'player_client': [client]}},
                    'user_agent': random.choice(USER_AGENTS),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filepath = ydl.prepare_filename(info)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 10240:
                        return {'file': filepath, 'method': f'یوتیوب ({client})', 'type': 'video'}
            except Exception as e:
                logger.error(f"YouTube {client} error: {e}")
        return None
    
    def method_aparat(self, url, cancellable=None):
        if 'aparat.com' in url:
            return download_aparat(url, cancellable)
        return None
    
    def method_telewebion(self, url, cancellable=None):
        if 'telewebion.com' in url:
            return download_telewebion(url, cancellable)
        return None
    
    def method_filimo(self, url, cancellable=None):
        if 'filimo.com' in url:
            return download_filimo(url, cancellable)
        return None
    
    def method_pinterest(self, url, cancellable=None):
        if 'pinterest.com' in url or 'pin.it' in url:
            return download_pinterest_image(url, cancellable)
        return None
    
    def method_ytdlp(self, url, cancellable=None):
        try:
            unique = f"{int(time.time()*1000)}"
            output = os.path.join(DOWNLOAD_PATH, f"general_{unique}.%(ext)s")
            ydl_opts = {
                'format': 'best',
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 3,
                'user_agent': random.choice(USER_AGENTS),
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                    return {'file': filepath, 'method': 'دانلودر عمومی', 'type': 'video'}
        except Exception as e:
            logger.error(f"General download error: {e}")
        return None
    
    def download(self, url, content_type_hint=None, progress_callback=None, cancellable=None):
        if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            result = download_image_direct(url, cancellable)
            if result:
                return result
        
        for i, method in enumerate(self.methods):
            if cancellable and cancellable.is_cancelled():
                return None
            
            if progress_callback:
                progress_callback(f"🔄 روش {i+1}: {self.method_names[i]}...")
            try:
                result = method(url, cancellable)
                if result:
                    return result
            except Exception as e:
                logger.error(f"Method {i+1} error: {e}")
            time.sleep(1)
        return None

downloader = UniversalDownloader()

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
        short_domains = ['bit.ly', 'tinyurl.com', 't.co', 'rb.gy', 'ow.ly', 'is.gd', 'buff.ly', 'pin.it']
        if any(d in urlparse(url).netloc for d in short_domains):
            resp = session_with_retry.get(url, allow_redirects=True, timeout=10, stream=True)
            resp.close()
            return resp.url
    except Exception as e:
        logger.error(f"Short URL resolve error: {e}")
    return url

def detect_platform(url):
    url = url.lower()
    platforms = {
        'یوتیوب': ['youtube.com', 'youtu.be'],
        'اینستاگرام': ['instagram.com'],
        'تیک‌تاک': ['tiktok.com'],
        'توییتر': ['twitter.com', 'x.com'],
        'پینترست': ['pinterest.com', 'pin.it'],
        'آپارات': ['aparat.com'],
        'تلوبیون': ['telewebion.com'],
        'فیلیمو': ['filimo.com', 'filimo.ir'],
        'نماشا': ['namasha.com'],
    }
    for platform, domains in platforms.items():
        if any(d in url for d in domains):
            return platform
    return "سایر"

# ================= ارسال با تلاش مجدد =================
def send_with_retry(chat_id, file_path, caption, file_type='video', max_retries=3):
    for attempt in range(max_retries):
        try:
            with open(file_path, 'rb') as f:
                if file_type == 'image':
                    return bot.send_photo(chat_id, f, caption=caption, timeout=300)
                elif file_type == 'audio':
                    return bot.send_audio(chat_id, f, caption=caption, timeout=300)
                else:
                    return bot.send_video(chat_id, f, caption=caption, timeout=300)
        except Exception as e:
            logger.error(f"Send attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                with open(file_path, 'rb') as f:
                    return bot.send_document(chat_id, f, caption=caption, timeout=300)

# ================= تابع اصلی دانلود =================
def process_download_task_with_cleanup(user_id, chat_id, url, content_type, is_audio_only, msg_id, request_id):
    file_path = None
    
    try:
        logger.info(f"Starting download for user {user_id}, request {request_id}")
        
        cancellable = download_queue.download_manager.register_download(user_id)
        
        hint = 'audio' if is_audio_only else None
        result = downloader.download(url, hint, cancellable=cancellable)
        
        if cancellable.is_cancelled():
            logger.info(f"Download cancelled for user {user_id}")
            bot.send_message(chat_id, "⏹️ **دانلود لغو شد!**", parse_mode="Markdown")
            return
        
        if result and result.get('file') and os.path.exists(result['file']):
            file_path = result['file']
            file_size = os.path.getsize(file_path)
            
            if file_size > MAX_FILE_SIZE:
                logger.warning(f"File too large for user {user_id}: {file_size}")
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE//(1024*1024)} مگابایت است!")
                return
            
            logger.info(f"Download successful for user {user_id}: {file_size} bytes")
            
            caption = f"✅ **دانلود شد!**\n📥 {result['method']}\n📊 {file_size/(1024*1024):.1f}MB"
            send_with_retry(chat_id, file_path, caption, result['type'])
            
            try:
                bot.edit_message_text("✅ **دانلود انجام شد!**", chat_id, msg_id)
            except Exception as e:
                logger.warning(f"Could not edit message: {e}")
        else:
            logger.error(f"Download failed for user {user_id}")
            bot.send_message(chat_id, "❌ **خطا در دانلود!**\nهمه روش‌ها امتحان شدند.")
    
    except Exception as e:
        logger.error(f"Process error for user {user_id}: {e}")
        bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")
    
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Cleaned up file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete file: {e}")
        
        download_queue.download_manager.remove_download(user_id)

# ================= دستورات بات =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    is_mem = check_membership_with_cache(user_id)
    
    if not is_mem:
        bot.reply_to(message, "🔒 **برای استفاده از ربات ابتدا در کانال عضو شوید.**", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    welcome_text = (
        "🎬 **ربات دانلود جهانی v15.0**\n\n"
        "🤖 **تشخیص خودکار عکس 📸 | فیلم 🎥 | آهنگ 🎵**\n\n"
        "✅ پشتیبانی از یوتیوب | اینستاگرام | تیک‌تاک\n"
        "✅ آپارات | تلوبیون | فیلیمو | نماشا\n"
        "✅ پینترست | توییتر | فیسبوک\n\n"
        f"⚡ محدودیت: {MAX_DOWNLOADS_PER_MINUTE} دانلود در دقیقه\n"
        f"⚙️ همزمان: {MAX_WORKERS} کاربر\n"
        f"📋 صف: {MAX_QUEUE_SIZE} درخواست\n"
        f"📥 حداکثر حجم: {MAX_FILE_SIZE//(1024*1024)}MB\n\n"
        "📌 **فقط کافیه لینک رو بفرستی!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    
    is_mem = check_membership_with_cache(user_id)
    if not is_mem:
        download_queue.add_pending_link(user_id, message.text)
        bot.reply_to(message, "🔒 **ابتدا در کانال عضو شوید.**", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    if download_queue.is_user_active(user_id):
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return
    
    allowed, remaining = download_queue.check_rate_limit(user_id)
    if not allowed:
        bot.reply_to(message, f"🛡️ **محدودیت سرعت!**\nحداکثر {MAX_DOWNLOADS_PER_MINUTE} دانلود در دقیقه.\n⏳ {remaining} ثانیه دیگر صبر کنید.")
        return
    
    if download_queue.is_queue_full():
        bot.reply_to(message, f"⚠️ **صف دانلود پر است!** ({MAX_QUEUE_SIZE} درخواست)\nلطفاً چند لحظه دیگر تلاش کنید.")
        return
    
    url = extract_url(message.text)
    if not url:
        bot.reply_to(message, "❌ لطفاً یک لینک معتبر بفرستید.")
        return
    
    resolved_url = resolve_short_url(url)
    if resolved_url != url:
        bot.send_message(message.chat.id, "🔗 **لینک کوتاه تشخیص داده شد.**", parse_mode="Markdown")
        url = resolved_url
    
    platform = detect_platform(url)
    msg = bot.send_message(message.chat.id, "🔍 **در حال تشخیص خودکار نوع محتوا...**", parse_mode="Markdown")
    content_type, type_name = detect_content_type_cached(url)
    
    type_emoji = {'image': '🖼️', 'video': '🎥', 'audio': '🎵'}.get(content_type, '📄')
    type_fa = {'image': 'عکس', 'video': 'ویدیو', 'audio': 'آهنگ'}.get(content_type, 'محتوای دیجیتال')
    
    bot.edit_message_text(f"{type_emoji} **تشخیص خودکار:** این لینک یک **{type_fa}** است!\n📱 **پلتفرم:** {platform}", message.chat.id, msg.message_id, parse_mode="Markdown")
    bot.reply_to(message, f"📥 **لطفاً نوع دانلود رو انتخاب کن:**", reply_markup=auto_keyboard(content_type), parse_mode="Markdown")
    
    request_id = hashlib.md5(f"{user_id}_{url}_{time.time()}".encode()).hexdigest()[:16]
    download_queue.add_user_request(user_id, url, content_type, request_id)
    
    with download_queue.stats_lock:
        download_queue.user_requests[f"temp_{user_id}"] = (url, content_type, request_id)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if call.data == "check_join":
        is_mem = is_member(user_id)
        download_queue.invalidate_membership_cache(user_id)
        download_queue.membership_cache.set(str(user_id), is_mem)
        
        if is_mem:
            bot.answer_callback_query(call.id, "عضویت تایید شد ✅")
            bot.edit_message_text("✅ عضویت شما تایید شد!", chat_id, call.message.message_id)
            pending_text = download_queue.get_pending_link(user_id)
            if pending_text:
                fake_message = type('obj', (object,), {
                    'from_user': type('obj', (object,), {'id': user_id})(),
                    'chat': type('obj', (object,), {'id': chat_id})(),
                    'text': pending_text
                })()
                handle(fake_message)
        else:
            bot.answer_callback_query(call.id, "هنوز عضو نیستید ❌")
            bot.edit_message_text("❌ **عضویت شما تأیید نشد!**\nلطفاً ابتدا در کانال عضو شوید.", chat_id, call.message.message_id, reply_markup=join_keyboard())
        return
    
    if call.data == "cancel":
        bot.edit_message_text("❌ عملیات لغو شد.", chat_id, call.message.message_id)
        return
    
    if call.data == "cancel_download":
        if download_queue.download_manager.cancel_download(user_id):
            bot.answer_callback_query(call.id, "دانلود لغو شد ✅")
            bot.edit_message_text("⏹️ **دانلود لغو شد!**", chat_id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "هیچ دانلود فعالی وجود ندارد ❌")
        return
    
    if download_queue.is_user_active(user_id):
        bot.answer_callback_query(call.id, "⏳ صبر کن دانلود قبلی تموم شه!")
        return
    
    with download_queue.stats_lock:
        temp_data = download_queue.user_requests.get(f"temp_{user_id}")
        if not temp_data:
            bot.answer_callback_query(call.id, "❌ خطا: لینک یافت نشد!")
            return
        url, content_type, request_id = temp_data
        del download_queue.user_requests[f"temp_{user_id}"]
    
    download_type = call.data
    is_audio_only = (download_type == 'audio')
    type_name = "ویدیو" if download_type == 'video' else ("آهنگ" if download_type == 'audio' else "تصویر")
    
    bot.edit_message_text(f"🔄 **در حال آماده‌سازی {type_name}...**\n⏳ لطفاً صبر کنید", chat_id, call.message.message_id, parse_mode="Markdown")
    
    added, position = download_queue.add_to_queue(user_id, chat_id, url, content_type, is_audio_only, call.message.message_id, request_id)
    
    if not added:
        bot.edit_message_text(f"⚠️ **صف دانلود پر است!**\nلطفاً چند لحظه دیگر تلاش کنید.", chat_id, call.message.message_id)
    else:
        bot.edit_message_text(f"🔄 **در صف انتظار...**\n📍 جایگاه شما: {position + 1}\n⏳ لطفاً صبر کنید", chat_id, call.message.message_id, parse_mode="Markdown")

# ================= دستورات ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    queue_size, active_count = download_queue.get_queue_info()
    
    text = f"👑 **پنل مدیریت v15.0**\n\n"
    text += f"✅ دانلود فعال: {active_count}/{MAX_WORKERS}\n"
    text += f"✅ صف انتظار: {queue_size}/{MAX_QUEUE_SIZE}\n"
    text += f"✅ کش عضویت: {len(download_queue.membership_cache.cache)}\n"
    text += f"✅ کش URL: {len(download_queue.url_cache.cache)}\n"
    text += f"✅ کانال اجباری: {REQUIRED_CHANNEL}\n"
    text += f"✅ حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB\n"
    text += f"✅ محدودیت: {MAX_DOWNLOADS_PER_MINUTE}/min\n"
    text += f"✅ تایم‌اوت: {DOWNLOAD_TIMEOUT}s"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['queue'])
def queue_status(message):
    if message.from_user.id != ADMIN_ID:
        return
    queue_size, active_count = download_queue.get_queue_info()
    bot.reply_to(message, f"📊 **وضعیت صف:**\n\nفعال: {active_count}\nصف: {queue_size}")

@bot.message_handler(commands=['clean'])
def clean_cache(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    download_queue.membership_cache.clear_expired()
    download_queue.url_cache.clear_expired()
    download_queue.cleanup_rate_limits()
    
    deleted = 0
    for f in os.listdir(DOWNLOAD_PATH):
        fpath = os.path.join(DOWNLOAD_PATH, f)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                deleted += 1
            except:
                pass
    
    bot.reply_to(message, f"✅ پاکسازی انجام شد!\nفایل‌های حذف شده: {deleted}")

# ================= وب‌هوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "🎬 ربات دانلود جهانی v15.0 فعال است!", 200

@app.route("/health", methods=["GET"])
def health():
    queue_size, active_count = download_queue.get_queue_info()
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "active_downloads": active_count,
        "queue_size": queue_size,
        "max_queue": MAX_QUEUE_SIZE,
        "max_workers": MAX_WORKERS,
        "cache_size": len(download_queue.membership_cache.cache)
    })

# ================= اجرا =================
if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود جهانی v15.0 - نسخه نهایی")
    print(f"✅ حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB")
    print(f"✅ محدودیت: {MAX_DOWNLOADS_PER_MINUTE} دانلود در دقیقه")
    print(f"✅ تردهای همزمان: {MAX_WORKERS}")
    print(f"✅ حداکثر صف: {MAX_QUEUE_SIZE}")
    print(f"✅ تایم‌اوت: {DOWNLOAD_TIMEOUT}s")
    print(f"✅ کش عضویت TTL: {MEMBERSHIP_TTL}s")
    print(f"✅ کانال اجباری: {REQUIRED_CHANNEL}")
    print("="*60)
    
    try:
        test_chat = bot.get_chat(REQUIRED_CHANNEL)
        logger.info(f"✅ Channel found: {test_chat.title}")
    except Exception as e:
        logger.error(f"⚠️ Channel connection error: {e}")
    
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"⚠️ Webhook error: {e}")
    
    app.run(host="0.0.0.0", port=PORT)
