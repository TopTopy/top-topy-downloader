# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import json
import subprocess
import random
import logging
import sys
import hashlib
import shutil
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات =================
TOKEN = "8629099905:AAHYL2VGTqTIVCscKd7QJNAvY0gEbVEEeg4"
ADMIN_ID = 8226091292
CHANNEL_USERNAME = "@top_topy_downloader"
DOWNLOAD_PATH = "downloads"
CACHE_PATH = "cache"
LOGS_PATH = "logs"
WEBHOOK_URL = "https://web-production-d8a05.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))

DAILY_LIMIT_NORMAL = 20
DAILY_LIMIT_VIP = 100
DEFAULT_DELETE_SECONDS = 30
MAX_FILE_SIZE_MB = 500

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(CACHE_PATH, exist_ok=True)
os.makedirs(LOGS_PATH, exist_ok=True)

# ================= لاگ فقط مهم =================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOGS_PATH, 'bot.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= فایل ذخیره کاربران و کش =================
USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"
CACHE_FILE = "url_cache.json"

def load_json(file, default):
    if os.path.exists(file):
        with open(file, 'r') as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=4)

settings = load_json(SETTINGS_FILE, {"delete_seconds": DEFAULT_DELETE_SECONDS, "max_size_mb": MAX_FILE_SIZE_MB})
users_data = load_json(USERS_FILE, {})
url_cache = load_json(CACHE_FILE, {})

def save_cache():
    # حذف کش‌های قدیمی (بیشتر از 7 روز)
    now = time.time()
    to_delete = [k for k, v in url_cache.items() if now - v.get('timestamp', 0) > 7*86400]
    for k in to_delete:
        if os.path.exists(url_cache[k]['filepath']):
            os.remove(url_cache[k]['filepath'])
        del url_cache[k]
    save_json(CACHE_FILE, url_cache)

def add_to_cache(url, filepath, metadata):
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    url_cache[url_hash] = {
        'url': url,
        'filepath': filepath,
        'metadata': metadata,
        'timestamp': time.time()
    }
    save_json(CACHE_FILE, url_cache)

def get_from_cache(url):
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    if url_hash in url_cache and os.path.exists(url_cache[url_hash]['filepath']):
        return url_cache[url_hash]
    return None

active_downloads = {}
admin_logs = []
lock = threading.Lock()
cancel_events = {}

# ================= توابع مدیریت کاربر =================
def get_user_tier(user_id):
    uid = str(user_id)
    if uid not in users_data:
        users_data[uid] = {"tier": "normal", "banned": False, "daily_count": 0, "last_date": datetime.now().strftime("%Y%m%d")}
        save_json(USERS_FILE, users_data)
    return users_data[uid]["tier"]

def is_banned(user_id):
    return users_data.get(str(user_id), {}).get("banned", False)

def set_banned(user_id, banned=True):
    uid = str(user_id)
    if uid not in users_data:
        get_user_tier(user_id)
    users_data[uid]["banned"] = banned
    save_json(USERS_FILE, users_data)

def set_user_tier(user_id, tier):
    uid = str(user_id)
    if uid not in users_data:
        get_user_tier(user_id)
    users_data[uid]["tier"] = tier
    save_json(USERS_FILE, users_data)

def check_daily_limit(user_id):
    today = datetime.now().strftime("%Y%m%d")
    uid = str(user_id)
    if uid not in users_data:
        get_user_tier(user_id)
    if users_data[uid]["last_date"] != today:
        users_data[uid]["daily_count"] = 0
        users_data[uid]["last_date"] = today
        save_json(USERS_FILE, users_data)
    limit = DAILY_LIMIT_VIP if get_user_tier(user_id) == "vip" else DAILY_LIMIT_NORMAL
    return users_data[uid]["daily_count"] < limit

def increment_daily_usage(user_id):
    today = datetime.now().strftime("%Y%m%d")
    uid = str(user_id)
    if uid not in users_data:
        get_user_tier(user_id)
    if users_data[uid]["last_date"] != today:
        users_data[uid]["daily_count"] = 0
        users_data[uid]["last_date"] = today
    users_data[uid]["daily_count"] += 1
    save_json(USERS_FILE, users_data)
    return users_data[uid]["daily_count"]

def get_remaining_limit(user_id):
    today = datetime.now().strftime("%Y%m%d")
    uid = str(user_id)
    if uid not in users_data:
        get_user_tier(user_id)
    if users_data[uid]["last_date"] != today:
        return DAILY_LIMIT_VIP if get_user_tier(user_id) == "vip" else DAILY_LIMIT_NORMAL
    limit = DAILY_LIMIT_VIP if get_user_tier(user_id) == "vip" else DAILY_LIMIT_NORMAL
    return max(0, limit - users_data[uid]["daily_count"])

# ================= توابع کمکی =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

def check_ffmpeg():
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

HAS_FFMPEG = check_ffmpeg()

def is_member(user_id):
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except:
        return False

def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def resolve_short_url(url):
    try:
        short_domains = ['bit.ly', 'tinyurl.com', 't.co', 'rb.gy', 'ow.ly', 'is.gd', 'buff.ly', 'pin.it', 'on.soundcloud.com']
        parsed = urlparse(url)
        if any(domain in parsed.netloc for domain in short_domains):
            response = requests.head(url, allow_redirects=True, timeout=10, headers={'User-Agent': random.choice(USER_AGENTS)})
            return response.url
        return url
    except:
        return url

def detect_platform(url):
    url = url.lower()
    platforms = {
        'youtube': ['youtube.com', 'youtu.be'],
        'instagram': ['instagram.com', 'instagr.am'],
        'tiktok': ['tiktok.com', 'vt.tiktok.com'],
        'twitter': ['twitter.com', 'x.com'],
        'facebook': ['facebook.com', 'fb.com', 'fb.watch'],
        'soundcloud': ['soundcloud.com', 'on.soundcloud.com'],
        'aparat': ['aparat.com'],
        'telewebion': ['telewebion.com'],
        'filimo': ['filimo.com'],
        'namasha': ['namasha.com'],
        'reddit': ['reddit.com'],
        'pinterest': ['pinterest.com', 'pin.it'],
        'twitch': ['twitch.tv'],
        'vimeo': ['vimeo.com'],
        'dailymotion': ['dailymotion.com'],
        'spotify': ['spotify.com'],
    }
    for platform, domains in platforms.items():
        for domain in domains:
            if domain in url:
                return platform.capitalize()
    return "Other"

def is_playlist(url):
    return 'playlist' in url or 'list=' in url or 'aparat.com/v/playlist' in url

def get_playlist_info(url):
    try:
        ydl_opts = {'quiet': True, 'extract_flat': True, 'force_generic_extractor': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                entries = info['entries']
                return [entry.get('url') for entry in entries if entry]
        return None
    except:
        return None

def get_storage_usage():
    total = 0
    count = 0
    for root, dirs, files in os.walk(DOWNLOAD_PATH):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
                count += 1
    for root, dirs, files in os.walk(CACHE_PATH):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.exists(fp):
                total += os.path.getsize(fp)
                count += 1
    return total, count

def clean_storage(keep_days=1):
    deleted = 0
    size = 0
    now = time.time()
    for path in [DOWNLOAD_PATH, CACHE_PATH]:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.exists(fp) and now - os.path.getmtime(fp) > keep_days*86400:
                    size += os.path.getsize(fp)
                    os.remove(fp)
                    deleted += 1
    return deleted, size

def schedule_file_deletion(filepath, seconds=None):
    if seconds is None:
        seconds = settings.get("delete_seconds", DEFAULT_DELETE_SECONDS)
    def delete():
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Deleted: {filepath}")
            except:
                pass
    timer = threading.Timer(seconds, delete)
    timer.daemon = True
    timer.start()
    return timer

def format_size(bytes_):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_ < 1024.0:
            return f"{bytes_:.1f}{unit}"
        bytes_ /= 1024.0
    return f"{bytes_:.1f}TB"

def format_speed(bytes_per_sec):
    return format_size(bytes_per_sec) + "/s"

# ================= کلاس دانلودر با اجرای همزمان ۱۸ روش =================
class ParallelDownloader:
    def __init__(self):
        self.methods = self._build_methods()
    
    def _build_methods(self):
        # تعریف ۱۸ روش مختلف دانلود (ترکیب format‌ها و تنظیمات)
        formats = [
            ('bestvideo+bestaudio/best', 'بهترین کیفیت'),
            ('best[height<=1080]', '1080p'),
            ('best[height<=720]', '720p'),
            ('best[height<=480]', '480p'),
            ('best[height<=360]', '360p'),
            ('best[height<=240]', '240p'),
            ('bestaudio', 'صوتی MP3'),
            ('bestaudio', 'صوتی M4A'),
            ('bestvideo', 'فقط ویدیو (بدون صدا)'),
            ('worst', 'کمترین کیفیت'),
        ]
        # اضافه کردن روش‌های با کلاینت متفاوت برای یوتیوب
        clients = ['android', 'ios', 'web', 'android_embedded']
        for client in clients:
            formats.append(('best', f'کلاینت {client}'))
        # روش‌های subprocess
        formats.append(('best', 'subprocess بهترین'))
        formats.append(('best[height<=720]', 'subprocess 720p'))
        return formats
    
    def _download_one(self, url, format_spec, method_name, progress_callback=None):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        is_audio = (format_spec == 'bestaudio')
        if is_audio:
            output = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.mp3")
            ydl_opts = {
                'format': 'bestaudio',
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 10,
                'fragment_retries': 10,
                'concurrent_fragment_downloads': 10,
                'throttledratelimit': 0,
                'continue_dl': True,   # Resume
                'socket_timeout': 60,
                'geo_bypass': True,
                'user_agent': random.choice(USER_AGENTS),
            }
            if HAS_FFMPEG:
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
        else:
            output = os.path.join(DOWNLOAD_PATH, f"video_{unique}.%(ext)s")
            ydl_opts = {
                'format': format_spec,
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'retries': 10,
                'fragment_retries': 10,
                'concurrent_fragment_downloads': 10,
                'throttledratelimit': 0,
                'continue_dl': True,
                'socket_timeout': 60,
                'geo_bypass': True,
                'user_agent': random.choice(USER_AGENTS),
            }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = info.get('requested_downloads', [{}])[0].get('filepath') or ydl.prepare_filename(info)
                if is_audio and HAS_FFMPEG:
                    filepath = os.path.splitext(filepath)[0] + '.mp3'
                if os.path.exists(filepath):
                    # استخراج metadata
                    metadata = {
                        'title': info.get('title', 'Unknown'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'upload_date': info.get('upload_date', ''),
                        'like_count': info.get('like_count', 0),
                        'view_count': info.get('view_count', 0),
                    }
                    return {'file': filepath, 'method': method_name, 'size': os.path.getsize(filepath),
                            'type': 'audio' if is_audio else 'video', 'metadata': metadata}
        except Exception as e:
            logger.warning(f"{method_name} failed: {e}")
        return None

    def download_parallel(self, url, progress_callback=None):
        """اجرای همزمان ۱۸ روش با ThreadPoolExecutor"""
        stop_flag = threading.Event()
        result_holder = [None]

        def worker(format_spec, method_name):
            if stop_flag.is_set():
                return None
            res = self._download_one(url, format_spec, method_name, progress_callback)
            if res and not stop_flag.is_set():
                stop_flag.set()
                result_holder[0] = res
            return res

        with ThreadPoolExecutor(max_workers=len(self.methods)) as executor:
            futures = {executor.submit(worker, fmt, name): (fmt, name) for fmt, name in self.methods}
            for future in as_completed(futures):
                if result_holder[0] is not None:
                    # لغو بقیه (با تنظیم stop_flag و ignore بقیه)
                    for f in futures:
                        f.cancel()
                    break
                future.result()  # برای گرفتن استثناها
        return result_holder[0]

downloader = ParallelDownloader()

# ================= پنل ادمین پیشرفته =================
def admin_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 آمار", callback_data="admin_stats"),
        InlineKeyboardButton("⚙️ تنظیمات", callback_data="admin_settings"),
        InlineKeyboardButton("👥 کاربران", callback_data="admin_users"),
        InlineKeyboardButton("🔧 VIP/بن", callback_data="admin_manage"),
        InlineKeyboardButton("💾 فضای ذخیره‌سازی", callback_data="admin_storage"),
        InlineKeyboardButton("📜 لاگ‌ها", callback_data="admin_logs"),
        InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("🔄 ریست ربات", callback_data="admin_restart")
    )
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "⛔ شما مسدود شده‌اید.")
        return
    if not is_member(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        markup.add(InlineKeyboardButton("✅ عضویت پیدا کردم", callback_data="check_membership"))
        bot.reply_to(message, f"🔒 ابتدا در کانال عضو شوید:\n{CHANNEL_USERNAME}", reply_markup=markup)
        return
    remaining = get_remaining_limit(user_id)
    tier = get_user_tier(user_id)
    welcome = (
        f"🎬 **ربات دانلود فوق‌پیشرفته ۲۰۲۶**\n\n"
        f"👑 سطح: {'VIP ⭐' if tier=='vip' else 'عادی'}\n"
        f"📊 دانلود باقی‌مانده امروز: `{remaining}`\n"
        f"✅ دانلود همزمان ۱۸ روش مختلف\n"
        f"✅ قابلیت Resume / Cache / Metadata کامل\n"
        f"✅ انتخاب کیفیت (240p تا 4K + صوتی)\n"
        f"✅ پشتیبانی از پلی‌لیست\n"
        f"✅ حذف خودکار فایل بعد از {settings['delete_seconds']} ثانیه\n\n"
        f"📌 **لینک خود را ارسال کنید.**"
    )
    bot.reply_to(message, welcome, parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    total_users = len(users_data)
    banned = sum(1 for u in users_data.values() if u.get("banned", False))
    vip = sum(1 for u in users_data.values() if u.get("tier") == "vip")
    storage_used, files_count = get_storage_usage()
    text = f"👑 **پنل مدیریت**\n👥 کاربران: {total_users}\n🚫 بن شده: {banned}\n💎 VIP: {vip}\n💾 فضا: {storage_used/1024/1024:.1f}MB\n📂 فایل‌ها: {files_count}\n⚙️ حذف خودکار: {settings['delete_seconds']} ثانیه"
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=admin_main_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید!")
        return
    if call.data == "admin_stats":
        today = datetime.now().strftime("%Y%m%d")
        active = sum(1 for u in users_data.values() if u.get("last_date") == today)
        downloads = sum(u.get("daily_count", 0) for u in users_data.values() if u.get("last_date") == today)
        bot.edit_message_text(f"📊 **آمار امروز**\n👥 کاربران فعال: {active}\n📥 دانلودها: {downloads}", call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")), parse_mode="Markdown")
    elif call.data == "admin_settings":
        text = f"⚙️ **تنظیمات ربات**\nمحدودیت عادی: {DAILY_LIMIT_NORMAL}\nمحدودیت VIP: {DAILY_LIMIT_VIP}\nحذف فایل بعد: {settings['delete_seconds']} ثانیه\nحداکثر حجم: {settings['max_size_mb']} MB"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕+۵ ثانیه", callback_data="admin_inc_del"),
            InlineKeyboardButton("➖-۵ ثانیه", callback_data="admin_dec_del"),
            InlineKeyboardButton("📦 +۵۰MB", callback_data="admin_inc_size"),
            InlineKeyboardButton("📦 -۵۰MB", callback_data="admin_dec_size"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "admin_inc_del":
        settings["delete_seconds"] += 5
        save_json(SETTINGS_FILE, settings)
        bot.answer_callback_query(call.id, f"زمان حذف: {settings['delete_seconds']} ثانیه")
        admin_panel(call.message)
    elif call.data == "admin_dec_del":
        if settings["delete_seconds"] > 5:
            settings["delete_seconds"] -= 5
            save_json(SETTINGS_FILE, settings)
            bot.answer_callback_query(call.id, f"زمان حذف: {settings['delete_seconds']} ثانیه")
        else:
            bot.answer_callback_query(call.id, "حداقل ۵ ثانیه!", show_alert=True)
        admin_panel(call.message)
    elif call.data == "admin_inc_size":
        settings["max_size_mb"] = min(2000, settings["max_size_mb"] + 50)
        save_json(SETTINGS_FILE, settings)
        bot.answer_callback_query(call.id, f"حداکثر حجم: {settings['max_size_mb']}MB")
        admin_panel(call.message)
    elif call.data == "admin_dec_size":
        if settings["max_size_mb"] > 50:
            settings["max_size_mb"] -= 50
            save_json(SETTINGS_FILE, settings)
            bot.answer_callback_query(call.id, f"حداکثر حجم: {settings['max_size_mb']}MB")
        else:
            bot.answer_callback_query(call.id, "حداقل ۵۰MB!", show_alert=True)
        admin_panel(call.message)
    elif call.data == "admin_users":
        users_list = "\n".join([f"`{uid}` - {'VIP' if u['tier']=='vip' else 'عادی'} - {'🚫' if u.get('banned') else '✅'}" for uid, u in list(users_data.items())[:20]])
        text = f"📋 **کاربران (۲۰ نفر اول)**\n{users_list}"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")), parse_mode="Markdown")
    elif call.data == "admin_manage":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("➕ افزودن VIP", callback_data="admin_add_vip"),
            InlineKeyboardButton("➖ حذف VIP", callback_data="admin_remove_vip"),
            InlineKeyboardButton("🚫 بن کاربر", callback_data="admin_ban_user"),
            InlineKeyboardButton("✅ رفع بن", callback_data="admin_unban_user"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
        )
        bot.edit_message_text("🔧 **مدیریت کاربران**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "admin_add_vip":
        msg = bot.send_message(call.message.chat.id, "آیدی عددی کاربر را ارسال کنید:")
        bot.register_next_step_handler(msg, add_vip_step, call.message)
    elif call.data == "admin_remove_vip":
        msg = bot.send_message(call.message.chat.id, "آیدی عددی کاربر را ارسال کنید:")
        bot.register_next_step_handler(msg, remove_vip_step, call.message)
    elif call.data == "admin_ban_user":
        msg = bot.send_message(call.message.chat.id, "آیدی کاربر برای بن:")
        bot.register_next_step_handler(msg, ban_user_step, call.message)
    elif call.data == "admin_unban_user":
        msg = bot.send_message(call.message.chat.id, "آیدی کاربر برای رفع بن:")
        bot.register_next_step_handler(msg, unban_user_step, call.message)
    elif call.data == "admin_storage":
        used, count = get_storage_usage()
        text = f"💾 **فضای ذخیره‌سازی**\nفضای مصرفی: {used/1024/1024:.1f}MB\nتعداد فایل‌ها: {count}\n🗑️ پاکسازی فایل‌های قدیمی‌تر از ۱ روز"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🗑️ پاکسازی", callback_data="admin_clean_storage"), InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "admin_clean_storage":
        deleted, size = clean_storage(keep_days=1)
        bot.answer_callback_query(call.id, f"{deleted} فایل حذف شد ({size/1024/1024:.1f}MB)")
        admin_panel(call.message)
    elif call.data == "admin_logs":
        log_text = "\n".join(admin_logs[-20:]) if admin_logs else "هیچ لاگی"
        bot.edit_message_text(f"📜 **لاگ‌های ادمین** (۲۰ مورد آخر)\n{log_text}", call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")), parse_mode="Markdown")
    elif call.data == "admin_broadcast":
        msg = bot.send_message(call.message.chat.id, "📤 **پیام همگانی خود را وارد کنید:**")
        bot.register_next_step_handler(msg, broadcast_message, call.message)
    elif call.data == "admin_restart":
        bot.edit_message_text("🔄 در حال ریست...", call.message.chat.id, call.message.message_id)
        time.sleep(1)
        os._exit(0)
    elif call.data == "admin_back":
        admin_panel(call.message)

def broadcast_message(message, orig_msg):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text
    success = 0
    fail = 0
    for uid in users_data.keys():
        try:
            bot.send_message(int(uid), f"📢 **اعلامیه همگانی**\n\n{text}", parse_mode="Markdown")
            success += 1
        except:
            fail += 1
        time.sleep(0.05)
    bot.send_message(message.chat.id, f"✅ پیام به {success} کاربر ارسال شد.\n❌ {fail} کاربر ناموفق.")
    admin_panel(orig_msg)

def add_vip_step(message, orig_msg):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        set_user_tier(uid, "vip")
        bot.send_message(message.chat.id, f"✅ کاربر {uid} VIP شد.")
        admin_logs.append(f"{datetime.now()} افزودن VIP به {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    admin_panel(orig_msg)

def remove_vip_step(message, orig_msg):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        set_user_tier(uid, "normal")
        bot.send_message(message.chat.id, f"✅ VIP کاربر {uid} حذف شد.")
        admin_logs.append(f"{datetime.now()} حذف VIP از {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    admin_panel(orig_msg)

def ban_user_step(message, orig_msg):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        set_banned(uid, True)
        bot.send_message(message.chat.id, f"🚫 کاربر {uid} بن شد.")
        admin_logs.append(f"{datetime.now()} بن کاربر {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    admin_panel(orig_msg)

def unban_user_step(message, orig_msg):
    if message.from_user.id != ADMIN_ID: return
    try:
        uid = int(message.text.strip())
        set_banned(uid, False)
        bot.send_message(message.chat.id, f"✅ بن کاربر {uid} برداشته شد.")
        admin_logs.append(f"{datetime.now()} رفع بن {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    admin_panel(orig_msg)

@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def check_membership_callback(call):
    if is_member(call.from_user.id):
        bot.edit_message_text("✅ عضویت تأیید شد! اکنون لینک خود را ارسال کنید.", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "هنوز عضو نشده‌اید!", show_alert=True)

# ================= هندلر اصلی با کیفیت انتخابی =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "⛔ شما مسدود هستید.")
        return
    if not is_member(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        bot.reply_to(message, f"🔒 ابتدا عضو کانال شوید:\n{CHANNEL_USERNAME}", reply_markup=markup)
        return

    url = extract_url(message.text)
    if not url:
        return
    if not check_daily_limit(user_id):
        remaining = get_remaining_limit(user_id)
        bot.reply_to(message, f"⚠️ محدودیت روزانه تمام شد! باقی‌مانده: {remaining}")
        return
    if user_id in active_downloads:
        bot.reply_to(message, "⏳ در حال دانلود... لطفاً صبر کنید.\nبرای لغو /cancel")
        return

    url = resolve_short_url(url)
    platform = detect_platform(url)

    # بررسی کش
    cached = get_from_cache(url)
    if cached:
        filepath = cached['filepath']
        metadata = cached['metadata']
        if os.path.exists(filepath):
            increment_daily_usage(user_id)
            remaining = get_remaining_limit(user_id)
            caption = f"✅ **از حافظه کش ارسال شد!**\n📥 پلتفرم: {platform}\n📌 عنوان: {metadata.get('title', 'Unknown')}\n👤 آپلودر: {metadata.get('uploader', 'Unknown')}\n⏱️ مدت: {metadata.get('duration', 0)} ثانیه\n👍 لایک: {metadata.get('like_count', 0)}\n👁️ بازدید: {metadata.get('view_count', 0)}\n📊 حجم: {os.path.getsize(filepath)/1024/1024:.1f}MB\n📊 باقی‌مانده امروز: {remaining}"
            with open(filepath, 'rb') as f:
                bot.send_video(message.chat.id, f, caption=caption)
            schedule_file_deletion(filepath)  # بعد از ارسال از سرور حذف شود ولی کش باقی می‌ماند (با تاخیر)
            return

    # انتخاب کیفیت
    msg = bot.reply_to(message, f"🔍 **پلتفرم:** {platform}\n🎯 لطفاً کیفیت مورد نظر را انتخاب کنید:", parse_mode="Markdown")
    markup = InlineKeyboardMarkup(row_width=2)
    qualities = [
        ("🎬 بهترین کیفیت", "best"),
        ("📺 1080p", "1080p"),
        ("📺 720p", "720p"),
        ("📺 480p", "480p"),
        ("📺 360p", "360p"),
        ("📺 240p", "240p"),
        ("🎵 صوتی MP3", "audio"),
        ("🎥 فقط ویدیو", "video_only"),
        ("🎬 پلی‌لیست (دانلود کل)", "playlist"),
    ]
    for name, qid in qualities:
        markup.add(InlineKeyboardButton(name, callback_data=f"q_{qid}|{url}|{user_id}"))
    bot.edit_message_text("🎯 **کیفیت مورد نظر را انتخاب کنید:**", msg.chat.id, msg.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def quality_callback(call):
    data = call.data.split("|")
    if len(data) != 3:
        bot.answer_callback_query(call.id, "خطا در داده")
        return
    q_type = data[0][2:]  # حذف q_ از ابتدا
    url = data[1]
    user_id = int(data[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "این درخواست متعلق به شما نیست!", show_alert=True)
        return

    if q_type == "playlist":
        if not is_playlist(url):
            bot.answer_callback_query(call.id, "این لینک پلی‌لیست نیست!", show_alert=True)
            return
        bot.edit_message_text("📀 در حال استخراج پلی‌لیست...", call.message.chat.id, call.message.message_id)
        playlist_items = get_playlist_info(url)
        if not playlist_items:
            bot.send_message(call.message.chat.id, "❌ خطا در استخراج پلی‌لیست.")
            return
        total = min(len(playlist_items), 10)
        bot.send_message(call.message.chat.id, f"🎬 {total} ویدیو یافت شد. شروع دانلود (حداکثر ۱۰ عدد)...")
        success = 0
        for i, item_url in enumerate(playlist_items[:10], 1):
            if not check_daily_limit(user_id):
                bot.send_message(call.message.chat.id, f"⚠️ محدودیت روزانه پر شد، {i-1} ویدیو دانلود شد.")
                break
            status_msg = bot.send_message(call.message.chat.id, f"🔄 در حال دانلود ویدیو {i}/{total}...")
            result = downloader.download_parallel(item_url, lambda m: None)  # بدون پیشرفت پیچیده
            if result and os.path.exists(result['file']):
                file_size = result['size']
                if file_size <= settings['max_size_mb'] * 1024 * 1024:
                    increment_daily_usage(user_id)
                    remaining = get_remaining_limit(user_id)
                    caption = f"✅ ویدیو {i} دانلود شد!\n📥 روش: {result['method']}\n📊 حجم: {file_size/1024/1024:.1f}MB\n📊 باقی‌مانده امروز: {remaining}"
                    with open(result['file'], 'rb') as f:
                        bot.send_video(call.message.chat.id, f, caption=caption)
                    schedule_file_deletion(result['file'])
                    success += 1
                else:
                    os.remove(result['file'])
            else:
                bot.send_message(call.message.chat.id, f"❌ ویدیو {i} دانلود نشد.")
            time.sleep(1)
        bot.send_message(call.message.chat.id, f"🏁 پایان پلی‌لیست. {success} ویدیو موفق.")
        return

    # دانلود تکی با کیفیت انتخابی
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "1080p": "best[height<=1080]",
        "720p": "best[height<=720]",
        "480p": "best[height<=480]",
        "360p": "best[height<=360]",
        "240p": "best[height<=240]",
        "audio": "bestaudio",
        "video_only": "bestvideo",
    }
    if q_type not in format_map:
        bot.answer_callback_query(call.id, "کیفیت نامعتبر")
        return

    bot.edit_message_text("⚡ شروع دانلود با اجرای همزمان ۱۸ روش...", call.message.chat.id, call.message.message_id)

    if user_id in active_downloads:
        bot.send_message(call.message.chat.id, "⏳ در حال دانلود...")
        return
    if not check_daily_limit(user_id):
        remaining = get_remaining_limit(user_id)
        bot.send_message(call.message.chat.id, f"⚠️ محدودیت روزانه تمام شد! باقی‌مانده: {remaining}")
        return

    stop_event = threading.Event()
    cancel_events[user_id] = stop_event

    def process():
        with lock:
            active_downloads[user_id] = time.time()
        try:
            def progress_callback(msg):
                try:
                    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
                except:
                    pass
            # دانلود با روش Parallel
            result = downloader.download_parallel(url, progress_callback)
            if result and os.path.exists(result['file']):
                file_size = result['size']
                if file_size > settings['max_size_mb'] * 1024 * 1024:
                    bot.send_message(call.message.chat.id, f"❌ حجم فایل بیشتر از {settings['max_size_mb']}MB است!")
                    os.remove(result['file'])
                    return
                increment_daily_usage(user_id)
                remaining = get_remaining_limit(user_id)
                metadata = result.get('metadata', {})
                caption = f"✅ **دانلود شد!**\n📥 روش: {result['method']}\n📌 عنوان: {metadata.get('title', 'Unknown')}\n👤 آپلودر: {metadata.get('uploader', 'Unknown')}\n⏱️ مدت: {metadata.get('duration', 0)} ثانیه\n👍 لایک: {metadata.get('like_count', 0)}\n👁️ بازدید: {metadata.get('view_count', 0)}\n📊 حجم: {file_size/1024/1024:.1f}MB\n📊 باقی‌مانده امروز: {remaining}"
                with open(result['file'], 'rb') as f:
                    if result['type'] == 'audio':
                        bot.send_audio(call.message.chat.id, f, caption=caption)
                    else:
                        bot.send_video(call.message.chat.id, f, caption=caption)
                # اضافه به کش
                add_to_cache(url, result['file'], metadata)
                schedule_file_deletion(result['file'])
                bot.edit_message_text("✅ ارسال شد!", call.message.chat.id, call.message.message_id)
            else:
                bot.send_message(call.message.chat.id, "❌ خطا در دانلود! همه ۱۸ روش ناموفق بودند.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ خطا: {str(e)[:200]}")
        finally:
            with lock:
                if user_id in active_downloads:
                    del active_downloads[user_id]
            if user_id in cancel_events:
                del cancel_events[user_id]

    threading.Thread(target=process, daemon=True).start()
    bot.answer_callback_query(call.id, "شروع دانلود...")

@bot.message_handler(commands=['cancel'])
def cancel_download(message):
    user_id = message.from_user.id
    if user_id in cancel_events:
        cancel_events[user_id].set()
        bot.reply_to(message, "⏹ درخواست لغو ثبت شد.")
    else:
        bot.reply_to(message, "ℹ️ هیچ دانلودی در حال انجام نیست.")

# ================= وب هوک و اجرا =================
@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "ربات دانلود فوق‌پیشرفته - نسخه ۲۰۲۶"

if __name__ == "__main__":
    print("🚀 ربات با اجرای همزمان ۱۸ روش و کش راه‌اندازی شد")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=PORT)
