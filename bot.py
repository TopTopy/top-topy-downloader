# -*- coding: utf-8 -*-
"""
GOD MODE Downloader Bot - نسخه نهایی
حالت Polling - بدون نیاز به Webhook
"""

import os
import re
import time
import threading
import random
import hashlib
import shutil
from collections import deque
from queue import Queue, Empty
from flask import Flask, jsonify
import telebot
import yt_dlp
import requests

# ================= تنظیمات مستقیم =================
TOKEN = "8629099905:AAHYL2VGTqTIVCscKd7QJNAvY0gEbVEEeg4"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 100 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
PORT = 8080

MAX_WORKERS = 2
MAX_QUEUE_SIZE = 20
MAX_DOWNLOADS_PER_MINUTE = 3

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= آمار و کش =================
stats = {'total': 0, 'today': 0, 'users': set()}
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

# ================= صف و مدیریت =================
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
        import subprocess
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        return True
    except:
        return False

FFMPEG_OK = check_ffmpeg()

# ================= کش فایل =================
def get_cache_key(url, quality):
    return hashlib.md5(f"{url}_{quality}".encode()).hexdigest()[:16]

def get_cached_file(url, quality):
    key = get_cache_key(url, quality)
    for ext in ['.mp4', '.mp3', '.jpg', '.png', '.gif', '.webm', '.mkv']:
        path = os.path.join(CACHE_PATH, f"{key}{ext}")
        if os.path.exists(path):
            os.utime(path, None)
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

# ================= دانلودر اصلی با yt-dlp =================
def download_with_ytdlp(url, is_audio=False, progress_callback=None):
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
        'user_agent': get_ua(),
        'extractor_args': {
            'youtube': {'player_client': ['android', 'ios', 'web']},
            'instagram': {'video': ['yes']},
            'tiktok': {'video': ['yes']},
        },
    }
    
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
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio and FFMPEG_OK:
                filename = os.path.splitext(filename)[0] + '.mp3'
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                return filename
    except Exception as e:
        print(f"Download error: {e}")
    return None

# ================= دانلود مستقیم اینستاگرام =================
def download_instagram_direct(url):
    try:
        shortcode = None
        patterns = [
            r'instagram\.com/p/([^/?]+)',
            r'instagram\.com/reel/([^/?]+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                shortcode = m.group(1)
                break
        
        if shortcode:
            api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=1"
            headers = {'User-Agent': get_ua(), 'Accept': 'application/json'}
            r = requests.get(api_url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                video_url = None
                if 'graphql' in data and 'shortcode_media' in data['graphql']:
                    media = data['graphql']['shortcode_media']
                    if media.get('is_video'):
                        video_url = media.get('video_url')
                if video_url:
                    unique = f"{int(time.time()*1000)}"
                    filename = os.path.join(DOWNLOAD_PATH, f"ig_{unique}.mp4")
                    vr = requests.get(video_url, headers=headers, stream=True)
                    if vr.status_code == 200:
                        with open(filename, 'wb') as f:
                            for chunk in vr.iter_content(8192):
                                if chunk:
                                    f.write(chunk)
                        return filename
    except Exception as e:
        print(f"Instagram error: {e}")
    return None

# ================= دانلود مستقیم پینترست =================
def download_pinterest_direct(url):
    try:
        pin_match = re.search(r'/pin/(\d+)', url)
        if not pin_match:
            try:
                r = requests.get(url, allow_redirects=True, timeout=10)
                pin_match = re.search(r'/pin/(\d+)', r.url)
            except:
                pass
        if pin_match:
            pin_id = pin_match.group(1)
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
            headers = {'User-Agent': get_ua(), 'Accept': 'application/json'}
            resp = requests.get(api_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
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
                                return filename
    except Exception as e:
        print(f"Pinterest error: {e}")
    return None

# ================= دانلود مستقیم تیک‌تاک =================
def download_tiktok_direct(url):
    try:
        unique = f"{int(time.time()*1000)}"
        output = os.path.join(DOWNLOAD_PATH, f"tt_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'quiet': True,
            'no_warnings': True,
            'user_agent': get_ua(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                return filename
    except Exception as e:
        print(f"TikTok error: {e}")
    return None

# ================= تابع اصلی دانلود =================
def download_media(url, is_audio=False, progress_callback=None):
    # بررسی کش
    cached = get_cached_file(url, '720')
    if cached:
        return cached
    
    url_lower = url.lower()
    
    # عکس مستقیم
    if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
        try:
            unique = f"{int(time.time()*1000)}"
            ext = '.jpg'
            for e in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                if e in url_lower:
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
                    cache_file(filename, url, '720')
                    return filename
        except:
            pass
    
    # اینستاگرام
    if 'instagram.com' in url_lower:
        result = download_instagram_direct(url)
        if result:
            cache_file(result, url, '720')
            return result
    
    # پینترست
    if 'pinterest.com' in url_lower or 'pin.it' in url_lower:
        result = download_pinterest_direct(url)
        if result:
            cache_file(result, url, '720')
            return result
    
    # تیک‌تاک
    if 'tiktok.com' in url_lower or 'vt.tiktok.com' in url_lower:
        result = download_tiktok_direct(url)
        if result:
            cache_file(result, url, '720')
            return result
    
    # یوتیوب و سایر
    result = download_with_ytdlp(url, is_audio, progress_callback)
    if result:
        cache_file(result, url, '720')
        return result
    
    return None

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
    return 'سایر'

def detect_content_type(url):
    u = url.lower()
    if any(ext in u for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
        return 'image', 'عکس', '🖼️'
    if any(ext in u for ext in ['.mp3', '.wav', '.ogg', '.m4a']):
        return 'audio', 'آهنگ', '🎵'
    return 'video', 'ویدیو', '🎬'

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

def safe_send(chat_id, file_path, caption):
    try:
        with open(file_path, 'rb') as f:
            try:
                return bot.send_video(chat_id, f, caption=caption, timeout=180)
            except:
                f.seek(0)
                return bot.send_document(chat_id, f, caption=caption, timeout=180)
    except Exception as e:
        print(f"Send error: {e}")
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
        except Exception as e:
            print(f"Worker error: {e}")

for _ in range(MAX_WORKERS):
    threading.Thread(target=queue_worker, daemon=True).start()

# ================= دستورات بات =================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    ff_status = "✅" if FFMPEG_OK else "❌"
    welcome = (
        "💣 **GOD MODE BOT**\n\n"
        "✅ پشتیبانی از:\n"
        "   ├ یوتیوب | اینستاگرام\n"
        "   ├ تیک‌تاک | پینترست\n"
        "   └ و سایر سایت‌ها\n\n"
        "✅ تشخیص خودکار فیلم / آهنگ / عکس\n"
        "✅ معماری پیشرفته Queue + Worker\n"
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
        f"⚡ دانلود فعال: {active}\n"
        f"📋 صف انتظار: {queue_size}/{MAX_QUEUE_SIZE}\n"
        f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}\n"
        f"💾 کش: {len(os.listdir(CACHE_PATH))} فایل"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    with active_lock:
        active = len(active_downloads)
    queue_size = download_queue.qsize()
    bot.reply_to(message, f"📊 **آمار ربات**\n\nفعال: {active}\nصف: {queue_size}\nکل دانلودها: {stats['total']}\nکاربران: {len(stats['users'])}", parse_mode="Markdown")

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
    bot.reply_to(message, f"📋 **وضعیت صف**\n\nدر حال دانلود: {active}\nدر انتظار: {queue_size}")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_msg(message):
    uid = message.from_user.id
    
    with active_lock:
        if uid in active_downloads:
            bot.reply_to(message, "⏳ در حال دانلود... لطفاً صبر کنید.")
            return
    
    allowed, rem = check_rate_limit(uid)
    if not allowed:
        bot.reply_to(message, f"🛡️ **محدودیت سرعت!**\n{rem} ثانیه دیگر صبر کنید.", parse_mode="Markdown")
        return
    
    if download_queue.qsize() >= MAX_QUEUE_SIZE:
        bot.reply_to(message, "⚠️ **صف دانلود پر است!**\nلطفاً چند دقیقه دیگر تلاش کنید.", parse_mode="Markdown")
        return
    
    url = extract_url(message.text)
    if not url:
        bot.reply_to(message, "❌ لینک نامعتبر! لطفاً یک لینک معتبر بفرستید.")
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
    
    safe_edit(f"🔄 در حال دانلود {cname}...", message.chat.id, msg.message_id)
    
    try:
        download_queue.put((uid, message.chat.id, url, is_audio, msg.message_id), timeout=5)
    except:
        with active_lock:
            active_downloads.pop(uid, None)
        safe_edit("⚠️ خطا در صف!", message.chat.id, msg.message_id)

# ================= سلامت سرویس =================
@app.route("/", methods=["GET"])
def home():
    return "💣 GOD MODE BOT ACTIVE - Polling Mode", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "active_downloads": len(active_downloads),
        "queue_size": download_queue.qsize(),
        "total_downloads": stats['total'],
        "users": len(stats['users']),
        "ffmpeg": FFMPEG_OK
    })

# ================= اجرا با Polling =================
def run_polling():
    while True:
        try:
            print("✅ ربات در حال اجرا است...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    print("="*60)
    print("💣 GOD MODE BOT - نسخه نهایی")
    print(f"✅ توکن: {TOKEN[:10]}...")
    print(f"✅ ادمین: {ADMIN_ID}")
    print(f"✅ FFmpeg: {'✅' if FFMPEG_OK else '❌'}")
    print(f"✅ Workers: {MAX_WORKERS}")
    print(f"✅ صف: {MAX_QUEUE_SIZE}")
    print(f"✅ حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB")
    print("="*60)
    
    # حذف webhook
    try:
        bot.remove_webhook()
        print("✅ Webhook removed")
    except Exception as e:
        print(f"Webhook removal: {e}")
    
    # استارت Polling در ترد جداگانه
    polling_thread = threading.Thread(target=run_polling, daemon=True)
    polling_thread.start()
    
    # استارت Flask برای Health Check
    print("✅ Flask server for health checks running on port", PORT)
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
