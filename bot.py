# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import subprocess
import random
import hashlib
import shutil
from collections import deque
from queue import Queue, Empty
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 100 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
PORT = int(os.getenv("PORT", 8080))
REQUIRED_CHANNEL = "@top_topy_downloader"
CHANNEL_LINK = "https://t.me/top_topy_downloader"

MAX_WORKERS = 2
MAX_QUEUE_SIZE = 15
MAX_DOWNLOADS_PER_MINUTE = 3

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= کش ساده =================
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
pending_links = {}
pending_lock = threading.Lock()

# ================= User-Agent =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
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

# ================= کش فایل =================
def get_cache_key(url, quality):
    return hashlib.md5(f"{url}_{quality}".encode()).hexdigest()[:16]

def get_cached_file(url, quality):
    key = get_cache_key(url, quality)
    for ext in ['.mp4', '.mp3', '.jpg', '.png']:
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

# ================= دانلود یوتیوب (بدون کوکی) =================
def download_youtube(url, quality='720', progress_callback=None):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    is_audio = (quality == 'audio')
    
    # روش‌های مختلف برای یوتیوب
    clients = ['android', 'ios', 'web', 'android_embedded']
    
    for client in clients:
        try:
            if is_audio:
                format_spec = 'bestaudio/best'
                output = os.path.join(DOWNLOAD_PATH, f"yt_audio_{unique}.%(ext)s")
            else:
                if quality == 'best':
                    format_spec = 'bestvideo+bestaudio/best'
                else:
                    format_spec = f'best[height<={quality}]/best'
                output = os.path.join(DOWNLOAD_PATH, f"yt_video_{unique}.%(ext)s")
            
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
                'extractor_args': {'youtube': {'player_client': [client]}}
            }
            
            if is_audio and FFMPEG_OK:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if is_audio and FFMPEG_OK:
                    filename = os.path.splitext(filename)[0] + '.mp3'
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'type': 'audio' if is_audio else 'video'}
        except Exception as e:
            print(f"YouTube {client} failed: {e}")
            continue
    
    return None

# ================= دانلود اینستاگرام (بدون کوکی) =================
def download_instagram(url):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    output = os.path.join(DOWNLOAD_PATH, f"ig_{unique}.%(ext)s")
    
    # روش‌های مختلف برای اینستاگرام
    ydl_opts_list = [
        {'format': 'best', 'extractor_args': {'instagram': {'video': ['yes']}}},
        {'format': 'bestvideo+bestaudio/best'},
        {'format': 'best'},
    ]
    
    for ydl_opts in ydl_opts_list:
        try:
            opts = {
                'format': ydl_opts.get('format', 'best'),
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 5,
                'user_agent': get_ua(),
            }
            if 'extractor_args' in ydl_opts:
                opts['extractor_args'] = ydl_opts['extractor_args']
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    is_video = filename.lower().endswith(('.mp4', '.mkv', '.webm'))
                    return {'file': filename, 'type': 'video' if is_video else 'image'}
        except Exception as e:
            print(f"Instagram method failed: {e}")
            continue
    
    return None

# ================= دانلود پینترست (بدون کوکی) =================
def download_pinterest(url):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    
    # استخراج ID پین
    pin_id = None
    pin_match = re.search(r'/pin/(\d+)', url)
    if pin_match:
        pin_id = pin_match.group(1)
    else:
        short_match = re.search(r'pin\.it/([a-zA-Z0-9]+)', url)
        if short_match:
            try:
                r = requests.get(url, allow_redirects=True, timeout=10)
                pin_match = re.search(r'/pin/(\d+)', r.url)
                if pin_match:
                    pin_id = pin_match.group(1)
            except:
                pass
    
    if pin_id:
        # روش اول: استفاده از API جایگزین
        try:
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
            headers = {'User-Agent': get_ua(), 'Accept': 'application/json'}
            r = requests.get(api_url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get('data') and len(data['data']) > 0:
                    images = data['data'][0].get('images', {})
                    for quality in ['orig', '736x', '564x']:
                        if quality in images:
                            img_url = images[quality]['url']
                            filename = os.path.join(DOWNLOAD_PATH, f"pin_{unique}.jpg")
                            img_r = requests.get(img_url, headers=headers, stream=True, timeout=30)
                            if img_r.status_code == 200:
                                with open(filename, 'wb') as f:
                                    for chunk in img_r.iter_content(8192):
                                        if chunk:
                                            f.write(chunk)
                                if os.path.getsize(filename) > 1024:
                                    return {'file': filename, 'type': 'image'}
        except Exception as e:
            print(f"Pinterest API failed: {e}")
    
    # روش دوم: yt-dlp
    try:
        output = os.path.join(DOWNLOAD_PATH, f"pin_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 5,
            'user_agent': get_ua(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                is_video = filename.lower().endswith(('.mp4', '.mkv', '.webm'))
                return {'file': filename, 'type': 'video' if is_video else 'image'}
    except Exception as e:
        print(f"Pinterest yt-dlp failed: {e}")
    
    return None

# ================= دانلود تیک‌تاک (بدون کوکی) =================
def download_tiktok(url):
    unique = f"{int(time.time()*1000)}{random.randint(100,999)}"
    output = os.path.join(DOWNLOAD_PATH, f"tt_{unique}.%(ext)s")
    
    # روش‌های مختلف برای تیک‌تاک
    for client in ['web', 'android', 'ios']:
        try:
            ydl_opts = {
                'format': 'best',
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 5,
                'user_agent': get_ua(),
                'extractor_args': {'tiktok': {'player_client': [client]}}
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if os.path.exists(filename) and os.path.getsize(filename) > 10240:
                    return {'file': filename, 'type': 'video'}
        except Exception as e:
            print(f"TikTok {client} failed: {e}")
            continue
    
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
    
    return 'video', 'ویدیو', '🎬'

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

# ================= تابع اصلی دانلود =================
def download_media(url, quality='720', progress_callback=None):
    cached = get_cached_file(url, quality)
    if cached:
        ftype = 'audio' if cached.endswith('.mp3') else ('image' if cached.endswith(('.jpg', '.png')) else 'video')
        return {'file': cached, 'type': ftype, 'cached': True}
    
    url_lower = url.lower()
    
    # پینترست
    if 'pinterest.com' in url_lower or 'pin.it' in url_lower:
        result = download_pinterest(url)
        if result:
            cache_file(result['file'], url, quality)
            return result
    
    # اینستاگرام
    if 'instagram.com' in url_lower:
        result = download_instagram(url)
        if result:
            cache_file(result['file'], url, quality)
            return result
    
    # تیک‌تاک
    if 'tiktok.com' in url_lower or 'vt.tiktok.com' in url_lower:
        result = download_tiktok(url)
        if result:
            cache_file(result['file'], url, quality)
            return result
    
    # یوتیوب
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        result = download_youtube(url, quality, progress_callback)
        if result:
            cache_file(result['file'], url, quality)
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
def process_download(user_id, chat_id, url, quality, msg_id):
    file_path = None
    result = None
    
    try:
        safe_edit("🔍 در حال آماده‌سازی...", chat_id, msg_id)
        result = download_media(url, quality, None)
        
        if result and result.get('file') and os.path.exists(result['file']):
            file_path = result['file']
            size = os.path.getsize(file_path)
            
            if size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE//(1024*1024)} مگابایت!")
                return
            
            type_name = {'image': 'تصویر', 'video': 'ویدیو', 'audio': 'آهنگ'}.get(result['type'], 'فایل')
            caption = f"✅ {type_name} دانلود شد! 📊 {size/(1024*1024):.1f}MB"
            
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
    
    ff = "✅" if FFMPEG_OK else "❌"
    welcome = (
        "🎬 **ربات دانلود هوشمند**\n\n"
        "✅ تشخیص خودکار فیلم / آهنگ / عکس\n"
        "✅ یوتیوب | اینستاگرام | تیک‌تاک | پینترست\n"
        f"🔧 FFmpeg: {ff}\n"
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
    
    quality = 'audio' if ctype == 'audio' else '720'
    
    with active_lock:
        active_downloads[uid] = time.time()
    
    safe_edit(f"🔄 دانلود {cname}...", message.chat.id, msg.message_id)
    
    try:
        download_queue.put((uid, message.chat.id, url, quality, msg.message_id), timeout=5)
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
    
    text = (
        "👑 **پنل مدیریت**\n\n"
        f"⚡ فعال: {active}\n"
        f"📋 صف: {queue_size}\n"
        f"💾 کش: {cache_files} فایل\n"
        f"🎬 FFmpeg: {'✅' if FFMPEG_OK else '❌'}\n"
        f"📥 حجم مجاز: {MAX_FILE_SIZE//(1024*1024)}MB"
    )
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🗑️ پاک کردن کش", callback_data="admin_clean"),
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
    return "Bot is running", 200

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "queue": download_queue.qsize()}, 200

# ================= اجرا =================
def run_polling():
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    print("="*50)
    print("🎬 ربات دانلود بدون کوکی")
    print(f"FFmpeg: {'✅' if FFMPEG_OK else '❌'}")
    print("="*50)
    
    try:
        bot.remove_webhook()
    except:
        pass
    
    threading.Thread(target=run_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
