# -*- coding: utf-8 -*-
"""
ربات دانلود هوشمند - نسخه نهایی کامل
پشتیبانی از: یوتیوب، اینستاگرام، تیک‌تاک، توییتر، آپارات، تلوبیون، فیلیمو، پینترست
قابلیت‌ها: تشخیص خودکار، کش هوشمند، صف دانلود، پنل ادمین کامل
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
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات اصلی =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
PORT = int(os.getenv("PORT", 8080))
REQUIRED_CHANNEL = "@top_topy_downloader"
CHANNEL_LINK = "https://t.me/top_topy_downloader"

# محدودیت‌ها
MAX_WORKERS = 2
MAX_QUEUE_SIZE = 15
MAX_DOWNLOADS_PER_MINUTE = 3
FILE_CACHE_TTL = 86400  # 24 ساعت

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= کش و دیتابیس درون حافظه =================
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

def clear_expired_cache():
    with cache_lock:
        now = time.time()
        expired = [k for k, (_, ts, ttl) in cache.items() if now - ts > ttl]
        for k in expired:
            del cache[k]
        return len(expired)

# ================= صف و مدیریت دانلود =================
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
print(f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}")

# ================= توابع کش فایل =================
def get_cache_key(url, quality):
    return hashlib.md5(f"{url}_{quality}".encode()).hexdigest()[:16]

def get_cached_file(url, quality):
    key = get_cache_key(url, quality)
    for ext in ['.mp4', '.mp3', '.mkv', '.webm', '.jpg', '.jpeg', '.png', '.gif']:
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
                return dest
            except:
                pass
    return file_path

def enforce_cache_limit(max_files=200):
    files = [os.path.join(CACHE_PATH, f) for f in os.listdir(CACHE_PATH) if os.path.isfile(os.path.join(CACHE_PATH, f))]
    if len(files) > max_files:
        files.sort(key=os.path.getmtime)
        for f in files[:len(files) - max_files]:
            try:
                os.remove(f)
            except:
                pass

# ================= پاکسازی دوره‌ای =================
def periodic_cleanup():
    while True:
        time.sleep(3600)
        try:
            # پاکسازی کش
            clear_expired_cache()
            enforce_cache_limit()
            
            # پاکسازی فایل‌های قدیمی
            now = time.time()
            for f in os.listdir(DOWNLOAD_PATH):
                path = os.path.join(DOWNLOAD_PATH, f)
                if os.path.isfile(path) and now - os.path.getmtime(path) > 3600:
                    os.remove(path)
            
            # پاکسازی rate limit قدیمی
            with rate_lock:
                now = time.time()
                to_delete = [uid for uid, times in user_rate_limit.items() 
                           if times and now - times[-1] > 86400]
                for uid in to_delete:
                    del user_rate_limit[uid]
            
            # آمار روزانه
            with active_lock:
                stats['today'] = 0
        except Exception as e:
            print(f"Cleanup error: {e}")

threading.Thread(target=periodic_cleanup, daemon=True).start()

# ================= به‌روزرسانی yt-dlp =================
def update_ytdlp():
    while True:
        time.sleep(86400)
        try:
            subprocess.run(["python", "-m", "pip", "install", "-U", "yt-dlp"], 
                          capture_output=True, timeout=120)
            print("yt-dlp updated")
        except:
            pass

threading.Thread(target=update_ytdlp, daemon=True).start()

# ================= تشخیص خودکار نوع محتوا =================
def detect_content_type(url):
    url_lower = url.lower()
    
    # پسوندها
    if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
        return 'image', 'عکس', '🖼️'
    if any(ext in url_lower for ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv']):
        return 'video', 'ویدیو', '🎬'
    if any(ext in url_lower for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac']):
        return 'audio', 'آهنگ', '🎵'
    
    # دامنه‌ها
    if any(d in url_lower for d in ['instagram.com/p/', 'pinterest.com', 'pin.it']):
        return 'image', 'عکس', '🖼️'
    if any(d in url_lower for d in ['soundcloud.com', 'spotify.com']):
        return 'audio', 'آهنگ', '🎵'
    
    # بررسی با yt-dlp
    try:
        opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'user_agent': get_ua()}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('vcodec') != 'none':
                return 'video', 'ویدیو', '🎬'
            if info.get('acodec') != 'none':
                return 'audio', 'آهنگ', '🎵'
    except:
        pass
    
    return 'video', 'ویدیو', '🎬'

def get_media_title(url):
    try:
        opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False, 'user_agent': get_ua()}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title', '')[:60]
    except:
        return ''

# ================= دانلود یوتیوب (اصلی) =================
def download_youtube(url, quality='720', progress_callback=None):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    is_audio = (quality == 'audio')
    
    if is_audio:
        format_spec = 'bestaudio/best'
    elif quality == 'best':
        format_spec = 'bestvideo+bestaudio/best'
    else:
        format_spec = f'bestvideo[height<={quality}]+bestaudio/best'
    
    output = os.path.join(DOWNLOAD_PATH, f"yt_{unique}.%(ext)s")
    
    ydl_opts = {
        'format': format_spec,
        'outtmpl': output,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 30,
        'user_agent': get_ua(),
        'extractor_args': {'youtube': {'player_client': ['android', 'ios', 'web']}}
    }
    
    if is_audio and FFMPEG_OK:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    
    last_pct = 0
    if progress_callback:
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
        ydl_opts['progress_hooks'] = [hook]
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio and FFMPEG_OK:
                filename = os.path.splitext(filename)[0] + '.mp3'
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                return {'file': filename, 'type': 'audio' if is_audio else 'video'}
    except Exception as e:
        print(f"YouTube error: {e}")
    return None

# ================= دانلود اینستاگرام =================
def download_instagram(url, progress_callback=None):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    output = os.path.join(DOWNLOAD_PATH, f"ig_{unique}.%(ext)s")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 5,
        'user_agent': get_ua(),
    }
    
    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                is_video = filename.lower().endswith(('.mp4', '.mkv', '.webm'))
                return {'file': filename, 'type': 'video' if is_video else 'image'}
    except Exception as e:
        print(f"Instagram error: {e}")
    return None

# ================= دانلود خودکار =================
def download_auto(url, quality='720', progress_callback=None):
    # بررسی کش
    cached = get_cached_file(url, quality)
    if cached:
        ftype = 'audio' if cached.endswith('.mp3') else ('image' if cached.endswith(('.jpg', '.png')) else 'video')
        return {'file': cached, 'type': ftype, 'cached': True}
    
    # لینک مستقیم تصویر
    if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
        try:
            unique = f"{int(time.time()*1000)}"
            ext = '.jpg'
            for e in ['.jpg', '.jpeg', '.png', '.gif']:
                if e in url.lower():
                    ext = e
                    break
            filename = os.path.join(DOWNLOAD_PATH, f"img_{unique}{ext}")
            r = requests.get(url, headers={'User-Agent': get_ua()}, stream=True, timeout=30)
            if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
                with open(filename, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                if os.path.getsize(filename) > 1024:
                    cache_file(filename, url, quality)
                    return {'file': filename, 'type': 'image'}
        except:
            pass
    
    url_lower = url.lower()
    
    # اینستاگرام
    if 'instagram.com' in url_lower:
        result = download_instagram(url, progress_callback)
        if result:
            cache_file(result['file'], url, quality)
            return result
    
    # یوتیوب
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        result = download_youtube(url, quality, progress_callback)
        if result:
            cache_file(result['file'], url, quality)
            return result
    
    # سایر پلتفرم‌ها
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    output = os.path.join(DOWNLOAD_PATH, f"dl_{unique}.%(ext)s")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 5,
        'user_agent': get_ua(),
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                cache_file(filename, url, quality)
                return {'file': filename, 'type': 'video'}
    except:
        pass
    
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
        r = requests.get(url, allow_redirects=True, timeout=10, stream=True)
        r.close()
        return r.url
    except:
        return url

def detect_platform(url):
    u = url.lower()
    if 'youtube.com' in u or 'youtu.be' in u:
        return 'یوتیوب'
    if 'instagram.com' in u:
        return 'اینستاگرام'
    if 'tiktok.com' in u:
        return 'تیک‌تاک'
    if 'twitter.com' in u or 'x.com' in u:
        return 'توییتر'
    if 'aparat.com' in u:
        return 'آپارات'
    if 'telewebion.com' in u:
        return 'تلوبیون'
    if 'filimo.com' in u:
        return 'فیلیمو'
    if 'pinterest.com' in u or 'pin.it' in u:
        return 'پینترست'
    return 'سایر'

# ================= بررسی عضویت =================
def is_member(user_id):
    try:
        m = bot.get_chat_member(REQUIRED_CHANNEL, int(user_id))
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

def check_membership(user_id):
    cached = get_cache(f"member_{user_id}")
    if cached is not None:
        return cached
    res = is_member(user_id)
    set_cache(f"member_{user_id}", res, 60)
    return res

def join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK),
        InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")
    )
    return markup

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
            return False, 60 - int(now - q[0])
        q.append(now)
        return True, None

# ================= ارسال فایل =================
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
def process_download(user_id, chat_id, url, quality, msg_id):
    file_path = None
    result = None
    
    def progress(msg):
        safe_edit(f"🔄 {msg}", chat_id, msg_id)
    
    try:
        safe_edit("🔍 در حال آماده‌سازی...", chat_id, msg_id)
        result = download_auto(url, quality, progress)
        
        if result and result.get('file') and os.path.exists(result['file']):
            file_path = result['file']
            size = os.path.getsize(file_path)
            
            if size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE//(1024*1024)} مگابایت!")
                return
            
            # به‌روزرسانی آمار
            with active_lock:
                stats['total'] += 1
                stats['today'] += 1
                stats['users'].add(user_id)
            
            type_name = {'image': 'تصویر', 'video': 'ویدیو', 'audio': 'آهنگ'}.get(result['type'], 'فایل')
            q_name = {'360': '360p', '720': '720p', '1080': '1080p', 'best': 'Best', 'audio': 'MP3'}.get(quality, '')
            q_text = f" ({q_name})" if q_name else ""
            caption = f"✅ {type_name}{q_text} دانلود شد! 📊 {size/(1024*1024):.1f}MB"
            
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
    if not check_membership(uid):
        bot.reply_to(message, "🔒 ابتدا در کانال عضو شوید.", reply_markup=join_keyboard(), parse_mode="Markdown")
        return
    
    ff_status = "✅" if FFMPEG_OK else "❌"
    welcome = (
        "🎬 **ربات دانلود هوشمند**\n\n"
        "✅ تشخیص خودکار فیلم / آهنگ / عکس\n"
        "✅ دانلود از یوتیوب، اینستاگرام، تیک‌تاک\n"
        "✅ آپارات، تلوبیون، فیلیمو، پینترست\n"
        f"🔧 FFmpeg: {ff_status}\n"
        f"📥 حداکثر حجم: {MAX_FILE_SIZE//(1024*1024)}MB\n\n"
        "📌 لینک را بفرستید..."
    )
    bot.reply_to(message, welcome, parse_mode="Markdown")

@bot.message_handler(content_types=['text'])
def handle_msg(message):
    uid = message.from_user.id
    
    if not check_membership(uid):
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
    content_type, type_name, type_emoji = detect_content_type(url)
    title = get_media_title(url)
    
    info = f"{type_emoji} **{type_name}**\n📱 {platform}"
    if title:
        info += f"\n📝 {title}"
    
    safe_edit(info, message.chat.id, msg.message_id)
    
    # انتخاب کیفیت پیش‌فرض
    if content_type == 'audio':
        quality = 'audio'
    elif content_type == 'image':
        quality = 'image'
    else:
        quality = '720'
    
    set_cache(f"user_{uid}_url", url)
    set_cache(f"user_{uid}_quality", quality)
    set_cache(f"user_{uid}_msg", msg.message_id)
    
    with active_lock:
        active_downloads[uid] = time.time()
    
    safe_edit(f"🔄 دانلود {type_name}...", message.chat.id, msg.message_id)
    
    try:
        download_queue.put((uid, message.chat.id, url, quality, msg.message_id), timeout=5)
    except:
        with active_lock:
            active_downloads.pop(uid, None)
        safe_edit("⚠️ خطا در صف!", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    
    if call.data == "check_join":
        mem = is_member(uid)
        set_cache(f"member_{uid}", mem, 60)
        
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

# ================= پنل ادمین کامل =================
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
        "👑 **پنل مدیریت ربات**\n\n"
        "📊 **آمار کلی:**\n"
        f"├ 👤 کاربران: {len(stats['users'])}\n"
        f"├ 📥 کل دانلودها: {stats['total']}\n"
        f"├ 📅 دانلود امروز: {stats['today']}\n"
        f"├ ⚡ دانلود فعال: {active}\n"
        f"└ 📋 صف انتظار: {queue_size}/{MAX_QUEUE_SIZE}\n\n"
        "💾 **وضعیت کش:**\n"
        f"├ 📁 تعداد فایل: {cache_files}\n"
        f"├ 💾 حجم کش: {cache_size:.1f}MB\n"
        f"└ 🔧 FFmpeg: {'✅' if FFMPEG_OK else '❌'}\n\n"
        "⚙️ **تنظیمات:**\n"
        f"├ حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB\n"
        f"├ محدودیت: {MAX_DOWNLOADS_PER_MINUTE}/min\n"
        f"├ Workers: {MAX_WORKERS}\n"
        f"└ کانال: {REQUIRED_CHANNEL}"
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
        deleted = 0
        for f in os.listdir(CACHE_PATH):
            try:
                os.remove(os.path.join(CACHE_PATH, f))
                deleted += 1
            except:
                pass
        bot.answer_callback_query(call.id, f"✅ {deleted} فایل کش پاک شد!")
        safe_edit(f"🗑️ {deleted} فایل کش پاک شد!", call.message.chat.id, call.message.message_id)
    
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
            f"💾 کش: {cache_f} فایل / {cache_sz:.1f}MB"
        )
        safe_edit(text, call.message.chat.id, call.message.message_id)
    
    elif call.data == "admin_purge":
        deleted = 0
        for f in os.listdir(DOWNLOAD_PATH):
            try:
                os.remove(os.path.join(DOWNLOAD_PATH, f))
                deleted += 1
            except:
                pass
        bot.answer_callback_query(call.id, f"✅ {deleted} فایل موقت پاک شد!")
        safe_edit(f"🧹 {deleted} فایل موقت پاک شد!", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    with active_lock:
        active = len(active_downloads)
    queue_size = download_queue.qsize()
    cache_f = len([f for f in os.listdir(CACHE_PATH) if os.path.isfile(os.path.join(CACHE_PATH, f))])
    bot.reply_to(message, f"📊 **آمار**\n\nفعال: {active}\nصف: {queue_size}\nکش: {cache_f} فایل\nکل دانلودها: {stats['total']}")

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
    bot.reply_to(message, f"📋 **وضعیت صف**\n\nفعال: {active}\nصف: {queue_size}")

# ================= Webhook و Health =================
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
    return "🎬 ربات دانلود هوشمند فعال است!", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "active": len(active_downloads),
        "queue": download_queue.qsize(),
        "total_downloads": stats['total'],
        "cache_size": len(os.listdir(CACHE_PATH)),
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
    print("🎬 ربات دانلود هوشمند - نسخه نهایی کامل")
    print(f"✅ FFmpeg: {'✅' if FFMPEG_OK else '❌'}")
    print(f"✅ حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB")
    print(f"✅ Workers: {MAX_WORKERS}")
    print(f"✅ صف: {MAX_QUEUE_SIZE}")
    print(f"✅ کانال: {REQUIRED_CHANNEL}")
    print("="*60)
    
    try:
        bot.remove_webhook()
        print("✅ Webhook removed")
    except:
        pass
    
    threading.Thread(target=run_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
