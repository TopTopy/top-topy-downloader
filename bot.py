# -*- coding: utf-8 -*-
"""
GOD MODE DOWNLOADER BOT v21.0
فقط با yt-dlp - بدون API مرده - بدون instaloader
پشتیبانی از: YouTube, Instagram, TikTok, Pinterest, Twitter, Facebook, Reddit, Vimeo, SoundCloud, Spotify, Twitch, آپارات, تلوبیون, فیلیمو, نماشا
"""

import os
import re
import time
import threading
import random
import hashlib
import shutil
import subprocess
from collections import deque
from queue import Queue, Empty
from flask import Flask, jsonify
import telebot
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات اصلی =================
TOKEN = "8629099905:AAHYL2VGTqTIVCscKd7QJNAvY0gEbVEEeg4"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 180 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
PORT = 8080

MAX_WORKERS = 3
MAX_QUEUE_SIZE = 30
MAX_DOWNLOADS_PER_MINUTE = 5
MAX_RETRIES = 3

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= آمار =================
stats = {'total': 0, 'today': 0, 'users': set()}

# ================= صف =================
download_queue = Queue(maxsize=MAX_QUEUE_SIZE)
active_downloads = {}
active_lock = threading.Lock()
user_rate_limit = {}
rate_lock = threading.Lock()

# ================= User-Agent =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
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
print(f"FFmpeg: {'✅' if FFMPEG_OK else '❌'}")

# ================= به‌روزرسانی خودکار yt-dlp =================
def update_ytdlp():
    try:
        subprocess.run(["pip", "install", "-U", "yt-dlp"], capture_output=True, timeout=60)
        print("yt-dlp updated")
    except:
        pass

threading.Thread(target=update_ytdlp, daemon=True).start()

# ================= کش فایل =================
def get_cache_key(url):
    return hashlib.md5(url.encode()).hexdigest()[:16]

def get_cached_file(url):
    key = get_cache_key(url)
    for ext in ['.mp4', '.mp3', '.jpg', '.png', '.gif', '.webm']:
        path = os.path.join(CACHE_PATH, f"{key}{ext}")
        if os.path.exists(path):
            return path
    return None

def cache_file(file_path, url):
    if file_path and os.path.exists(file_path):
        key = get_cache_key(url)
        ext = os.path.splitext(file_path)[1].lower()
        dest = os.path.join(CACHE_PATH, f"{key}{ext}")
        if not os.path.exists(dest):
            try:
                shutil.move(file_path, dest)
            except:
                pass

# ================= ONLY yt-dlp (موتور اصلی) =================
def download_with_ytdlp(url, is_audio=False, progress_callback=None):
    """فقط yt-dlp - تنها روش پایدار"""
    clients = ['android', 'ios', 'web', 'android_embedded']
    
    for attempt in range(MAX_RETRIES):
        for client in clients:
            try:
                unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
                
                if is_audio:
                    format_spec = 'bestaudio/best'
                    output = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.%(ext)s")
                else:
                    format_spec = 'best[height<=720]/best'
                    output = os.path.join(DOWNLOAD_PATH, f"video_{unique}.%(ext)s")
                
                ydl_opts = {
                    'format': format_spec,
                    'outtmpl': output,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'retries': 15,
                    'fragment_retries': 15,
                    'socket_timeout': 30,
                    'extractor_retries': 5,
                    'user_agent': get_ua(),
                    'extractor_args': {
                        'youtube': {'player_client': [client]},
                        'instagram': {'video': ['yes']},
                        'tiktok': {'video': ['yes']},
                    },
                }
                
                # کوکی در صورت وجود
                if os.path.exists('cookies.txt'):
                    ydl_opts['cookiefile'] = 'cookies.txt'
                else:
                    ydl_opts['cookiefile'] = None
                
                if is_audio and FFMPEG_OK:
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                
                if progress_callback:
                    def hook(d):
                        if d['status'] == 'downloading':
                            pct = d.get('_percent_str', '0%').replace('%', '').strip()
                            progress_callback(f"⬇️ {pct}%")
                        elif d['status'] == 'finished':
                            progress_callback("✅ نهایی‌سازی...")
                    ydl_opts['progress_hooks'] = [hook]
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    if is_audio and FFMPEG_OK:
                        filename = os.path.splitext(filename)[0] + '.mp3'
                    if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                        return filename
            except Exception as e:
                print(f"yt-dlp {client} attempt {attempt+1} failed: {e}")
                continue
        
        if attempt < MAX_RETRIES - 1:
            time.sleep(2)
    
    return None

# ================= لایه 2: دانلود مستقیم عکس (فال بک) =================
def download_image_direct(url):
    try:
        unique = f"{int(time.time()*1000)}"
        ext = '.jpg'
        for e in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            if e in url.lower():
                ext = e
                break
        filename = os.path.join(DOWNLOAD_PATH, f"img_{unique}{ext}")
        headers = {'User-Agent': get_ua()}
        r = requests.get(url, headers=headers, stream=True, timeout=30)
        if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(filename) > 1024:
                return filename
    except:
        pass
    return None

# ================= رفع لینک کوتاه =================
def resolve_short_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url

# ================= تشخیص پلتفرم =================
def detect_platform(url):
    u = url.lower()
    if 'youtube.com' in u or 'youtu.be' in u:
        return 'یوتیوب'
    if 'instagram.com' in u:
        return 'اینستاگرام'
    if 'tiktok.com' in u or 'vt.tiktok.com' in u:
        return 'تیک‌تاک'
    if 'pinterest.com' in u or 'pin.it' in u:
        return 'پینترست'
    if 'twitter.com' in u or 'x.com' in u:
        return 'توییتر'
    if 'facebook.com' in u:
        return 'فیسبوک'
    if 'reddit.com' in u:
        return 'ردیت'
    if 'vimeo.com' in u:
        return 'ویمئو'
    if 'soundcloud.com' in u:
        return 'ساوندکلاود'
    if 'spotify.com' in u:
        return 'اسپاتیفای'
    if 'twitch.tv' in u:
        return 'تویچ'
    if 'aparat.com' in u:
        return 'آپارات'
    if 'telewebion.com' in u:
        return 'تلوبیون'
    return 'سایر'

def detect_content_type(url):
    u = url.lower()
    if any(ext in u for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
        return 'image', 'عکس', '🖼️'
    if any(ext in u for ext in ['.mp3', '.wav', '.ogg', '.m4a']):
        return 'audio', 'آهنگ', '🎵'
    return 'video', 'ویدیو', '🎬'

def extract_url(text):
    urls = re.findall(r'https?://[^\s<>()\[\]{}\n]+', text)
    if urls:
        url = urls[0]
        while url and url[-1] in '.,!?;:)]}':
            url = url[:-1]
        return url
    return None

# ================= موتور اصلی دانلود (Pipeline ساده) =================
def download_media(url, is_audio=False, progress_callback=None):
    # بررسی کش
    cached = get_cached_file(url)
    if cached:
        return cached
    
    # رفع لینک کوتاه
    url = resolve_short_url(url)
    
    # عکس مستقیم (فال بک)
    if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
        result = download_image_direct(url)
        if result:
            cache_file(result, url)
            return result
    
    # فقط yt-dlp برای همه چیز
    result = download_with_ytdlp(url, is_audio, progress_callback)
    if result:
        cache_file(result, url)
        return result
    
    return None

# ================= Rate Limit =================
def check_rate_limit(user_id):
    with rate_lock:
        now = time.time()
        if user_id not in user_rate_limit:
            user_rate_limit[user_id] = deque(maxlen=MAX_DOWNLOADS_PER_MINUTE)
        q = user_rate_limit[user_id]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= MAX_DOWNLOADS_PER_MINUTE:
            remaining = 60 - int(now - q[0])
            return False, remaining
        q.append(now)
        return True, 0

# ================= ارسال ایمن =================
def safe_send(chat_id, file_path, caption):
    try:
        with open(file_path, 'rb') as f:
            try:
                return bot.send_video(chat_id, f, caption=caption, timeout=180)
            except:
                f.seek(0)
                return bot.send_document(chat_id, f, caption=caption, timeout=180)
    except:
        return None

def safe_edit(text, chat_id, msg_id):
    try:
        bot.edit_message_text(text, chat_id, msg_id, parse_mode='Markdown')
    except:
        pass

# ================= پردازش دانلود =================
def process_download(user_id, chat_id, url, is_audio, msg_id):
    file_path = None
    
    def progress(msg):
        safe_edit(f"🔄 {msg}", chat_id, msg_id)
    
    try:
        safe_edit("🔍 در حال آماده‌سازی...", chat_id, msg_id)
        file_path = download_media(url, is_audio, progress)
        
        if file_path and os.path.exists(file_path):
            size = os.path.getsize(file_path)
            if size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE//(1024*1024)} مگابایت!")
                return
            
            with active_lock:
                stats['total'] += 1
                stats['today'] += 1
                stats['users'].add(user_id)
            
            type_name = 'ویدیو' if not is_audio else 'آهنگ'
            caption = f"✅ {type_name} دانلود شد!\n📊 {size/(1024*1024):.1f}MB"
            safe_send(chat_id, file_path, caption)
            safe_edit("✅ انجام شد!", chat_id, msg_id)
        else:
            bot.send_message(chat_id, "❌ خطا در دانلود!")
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطا: {str(e)[:100]}")
    finally:
        if file_path and os.path.exists(file_path):
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
        except:
            pass

for _ in range(MAX_WORKERS):
    threading.Thread(target=queue_worker, daemon=True).start()

# ================= دستورات بات =================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    ff_status = "✅" if FFMPEG_OK else "❌"
    welcome = (
        "💣 **GOD MODE BOT v21.0**\n\n"
        "✅ فقط yt-dlp (پایدارترین روش)\n"
        "✅ پشتیبانی از:\n"
        "   ├ یوتیوب | اینستاگرام | تیک‌تاک\n"
        "   ├ پینترست | توییتر | فیسبوک\n"
        "   ├ ردیت | ویمئو | ساوندکلاود\n"
        "   ├ اسپاتیفای | تویچ | آپارات\n"
        "   └ تلوبیون | فیلیمو | نماشا\n\n"
        f"🔧 FFmpeg: {ff_status}\n"
        f"📥 حداکثر حجم: {MAX_FILE_SIZE//(1024*1024)}MB\n\n"
        "📌 لینک را بفرستید..."
    )
    bot.reply_to(message, welcome, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    with active_lock:
        active = len(active_downloads)
    queue_size = download_queue.qsize()
    
    text = (
        "👑 **پنل مدیریت**\n\n"
        f"👤 کاربران: {len(stats['users'])}\n"
        f"📥 کل دانلودها: {stats['total']}\n"
        f"⚡ فعال: {active}\n"
        f"📋 صف: {queue_size}\n"
        f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    with active_lock:
        active = len(active_downloads)
    bot.reply_to(message, f"📊 آمار\nفعال: {active}\nکل: {stats['total']}")

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
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
            d += 1
        except:
            pass
    bot.reply_to(message, f"✅ {d} فایل پاک شد!")

@bot.message_handler(commands=['queue'])
def queue_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    queue_size = download_queue.qsize()
    with active_lock:
        active = len(active_downloads)
    bot.reply_to(message, f"📋 وضعیت صف\nدر حال دانلود: {active}\nدر انتظار: {queue_size}")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_msg(message):
    uid = message.from_user.id
    
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
    
    with active_lock:
        active_downloads[uid] = time.time()
    
    safe_edit(f"🔄 دانلود {cname}...", message.chat.id, msg.message_id)
    
    try:
        download_queue.put((uid, message.chat.id, url, is_audio, msg.message_id), timeout=5)
    except:
        with active_lock:
            active_downloads.pop(uid, None)
        safe_edit("⚠️ خطا!", message.chat.id, msg.message_id)

# ================= سلامت سرویس =================
@app.route("/", methods=["GET"])
def home():
    return "💣 GOD MODE BOT v21.0 ACTIVE", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "active": len(active_downloads),
        "queue": download_queue.qsize(),
        "total": stats['total']
    })

# ================= اجرا =================
if __name__ == "__main__":
    print("="*60)
    print("💣 GOD MODE BOT v21.0")
    print(f"FFmpeg: {'✅' if FFMPEG_OK else '❌'}")
    print(f"Workers: {MAX_WORKERS}")
    print(f"Queue: {MAX_QUEUE_SIZE}")
    print("="*60)
    
    try:
        bot.remove_webhook()
    except:
        pass
    
    def run_polling():
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
            except:
                time.sleep(10)
    
    threading.Thread(target=run_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
