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
import glob
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import requests
from urllib.parse import urlparse

# ================= تنظیمات =================
TOKEN = "8629099905:AAEBpbyDcVI35-C3i0OKDnnXAq5ut0KtQ5w"
ADMIN_IDS = [8226091292]  # لیست ادمین‌ها (می‌توانید چند تا اضافه کنید)
CHANNEL_USERNAME = "@top_topy_downloader"
MAX_FILE_SIZE = 500 * 1024 * 1024
DOWNLOAD_PATH = "downloads"
LOGS_PATH = "logs"

DAILY_LIMIT_NORMAL = 20
DAILY_LIMIT_VIP = 100
FILE_DELETE_SECONDS = 30

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(LOGS_PATH, exist_ok=True)

# ================= لاگ =================
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
# ================= فایل ذخیره کاربران =================
USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"

def load_json(file, default):
    if os.path.exists(file):
        with open(file, 'r') as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=4)

users_data = load_json(USERS_FILE, {})
settings = load_json(SETTINGS_FILE, {"delete_seconds": FILE_DELETE_SECONDS, "max_size_mb": MAX_FILE_SIZE//(1024*1024)})

# ================= توابع کاربری =================
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
        'clips': ['clips.ir'],
        'tamasha': ['tamasha.com'],
    }
    for platform, domains in platforms.items():
        for domain in domains:
            if domain in url:
                return platform.capitalize()
    return "Other"

def get_storage_usage():
    total = 0
    count = 0
    for root, dirs, files in os.walk(DOWNLOAD_PATH):
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
    for root, dirs, files in os.walk(DOWNLOAD_PATH):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.exists(fp) and now - os.path.getmtime(fp) > keep_days*86400:
                size += os.path.getsize(fp)
                os.remove(fp)
                deleted += 1
    return deleted, size

def schedule_file_deletion(filepath):
    def delete():
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Deleted: {filepath}")
    timer = threading.Timer(settings.get("delete_seconds", FILE_DELETE_SECONDS), delete)
    timer.daemon = True
    timer.start()

# ================= کلاس دانلودر (بهینه برای یوتیوب) =================
class YouTubeDownloader:
    def __init__(self):
        self.methods = []
        # فقط روش‌های ضروری و به ترتیب اولویت
        if HAS_FFMPEG:
            self.methods.append(('bestvideo+bestaudio/best', 'بهترین کیفیت (ترکیبی)'))
        self.methods.append(('best', 'بهترین کیفیت موجود'))
        self.methods.append(('bestvideo[height<=720]+bestaudio/best[height<=720]', '720p'))
        self.methods.append(('best[height<=480]', '480p'))
        self.methods.append(('bestaudio', 'صوتی MP3'))
        self.methods.append(('worst', 'کمترین کیفیت'))

    def _download(self, url, format_spec, method_name):
        # تبدیل لینک shorts به معمولی
        if 'youtube.com/shorts/' in url:
            url = url.replace('/shorts/', '/watch?v=')
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        is_audio = (format_spec == 'bestaudio')
        if is_audio:
            output_template = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.mp3")
        else:
            output_template = os.path.join(DOWNLOAD_PATH, f"video_{unique}.%(ext)s")

        ydl_opts = {
            'format': format_spec,
            'outtmpl': output_template,
            'noplaylist': True,
            'quiet': False,       # برای دیباگ (در نهایت می‌تونی True کنی)
            'no_warnings': False,
            'verbose': True,      # برای دیدن جزئیات خطا
            'retries': 5,
            'fragment_retries': 5,
            'concurrent_fragment_downloads': 3,  # کاهش همزمانی برای جلوگیری از 429
            'throttledratelimit': 0,
            'socket_timeout': 60,
            'geo_bypass': True,
            'user_agent': random.choice(USER_AGENTS),
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],  # اولویت با android
                }
            }
        }
        if is_audio and HAS_FFMPEG:
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # پیدا کردن فایل واقعی دانلود شده
                base = ydl.prepare_filename(info)
                if is_audio and HAS_FFMPEG:
                    base = os.path.splitext(base)[0] + '.mp3'
                # اگر دقیقاً همان فایل وجود نداشت، با الگو جستجو کن
                if not os.path.exists(base):
                    pattern = base.replace('%(ext)s', '*')
                    files = glob.glob(pattern)
                    if files:
                        base = files[0]
                if os.path.exists(base):
                    metadata = {
                        'title': info.get('title', 'Unknown'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'upload_date': info.get('upload_date', ''),
                        'like_count': info.get('like_count', 0),
                        'view_count': info.get('view_count', 0),
                    }
                    return {'file': base, 'method': method_name, 'size': os.path.getsize(base),
                            'type': 'audio' if is_audio else 'video', 'metadata': metadata}
        except Exception as e:
            logger.error(f"{method_name} failed: {e}")
        return None

    def download(self, url, progress_callback=None):
        # اجرای روش‌ها به ترتیب (نه همزمان) برای جلوگیری از 429
        for fmt, name in self.methods:
            if progress_callback:
                progress_callback(f"🔄 تلاش: {name}...")
            result = self._download(url, fmt, name)
            if result:
                return result
            time.sleep(1)  # فاصله بین روش‌ها
        return None

downloader = YouTubeDownloader()
active_downloads = {}
admin_logs = []
lock = threading.Lock()
cancel_events = {}

# ================= منوی اصلی با دکمه‌های شیشه‌ای =================
def main_menu_keyboard(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{bot.get_me().username}?startgroup=true"),
        InlineKeyboardButton("📚 راهنما", callback_data="help_menu"),
        InlineKeyboardButton("📊 آمار من", callback_data="my_stats"),
        InlineKeyboardButton("📢 کانال ما", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"),
    )
    if user_id in ADMIN_IDS:
        markup.add(InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel_from_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "help_menu")
def help_menu_callback(call):
    text = (
        "📚 **راهنمای سریع ربات**\n\n"
        "1️⃣ لینک خود را از یوتیوب، اینستاگرام، تیک‌تاک، آپارات و... ارسال کنید.\n"
        "2️⃣ ربات بهترین کیفیت ممکن را دانلود و برایتان ارسال می‌کند.\n"
        "3️⃣ فایل‌ها پس از ۳۰ ثانیه از سرور پاک می‌شوند.\n"
        "4️⃣ هر کاربر روزانه ۲۰ دانلود رایگان دارد (VIPها ۱۰۰ دانلود).\n"
        "5️⃣ برای لغو دانلود، دستور /cancel را بفرستید.\n\n"
        "✅ در صورت مشکل با ادمین تماس بگیرید."
    )
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "my_stats")
def my_stats_callback(call):
    user_id = call.from_user.id
    tier = get_user_tier(user_id)
    remaining = get_remaining_limit(user_id)
    daily_used = (DAILY_LIMIT_VIP if tier=='vip' else DAILY_LIMIT_NORMAL) - remaining
    total_downloads = users_data.get(str(user_id), {}).get("daily_count", 0)
    text = (
        f"📊 **آمار شما**\n\n"
        f"👑 سطح: {'VIP ⭐' if tier=='vip' else 'عادی'}\n"
        f"📥 دانلود امروز: {daily_used} از {DAILY_LIMIT_VIP if tier=='vip' else DAILY_LIMIT_NORMAL}\n"
        f"✅ باقی‌مانده امروز: {remaining}\n"
        f"🔢 کل دانلودهای انجام شده: {total_downloads}"
    )
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    user_id = call.from_user.id
    remaining = get_remaining_limit(user_id)
    tier = get_user_tier(user_id)
    welcome = (
        f"🎬 **ربات دانلود فوق‌پیشرفته ۲۰۲۶**\n\n"
        f"👑 سطح: {'VIP ⭐' if tier=='vip' else 'عادی'}\n"
        f"📊 دانلود باقی‌مانده امروز: `{remaining}`\n\n"
        f"✅ فقط کافیست لینک خود را ارسال کنید.\n"
        f"🚀 ربات به‌طور خودکار بهترین کیفیت را دانلود می‌کند."
    )
    bot.edit_message_text(welcome, call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")

# ================= پنل ادمین (با تابع مجزا) =================
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

def show_admin_panel(chat_id):
    total_users = len(users_data)
    banned = sum(1 for u in users_data.values() if u.get("banned", False))
    vip = sum(1 for u in users_data.values() if u.get("tier") == "vip")
    storage_used, files_count = get_storage_usage()
    text = f"👑 **پنل مدیریت**\n👥 کاربران: {total_users}\n🚫 بن شده: {banned}\n💎 VIP: {vip}\n💾 فضا: {storage_used/1024/1024:.1f}MB\n📂 فایل‌ها: {files_count}\n⚙️ حذف خودکار: {settings.get('delete_seconds', FILE_DELETE_SECONDS)} ثانیه"
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=admin_main_keyboard())

# ================= هندلرها =================
@bot.message_handler(commands=['id'])
def show_id(message):
    bot.reply_to(message, f"🆔 آیدی شما: `{message.from_user.id}`", parse_mode="Markdown")

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
        f"📊 دانلود باقی‌مانده امروز: `{remaining}`\n\n"
        f"✅ فقط کافیست لینک خود را ارسال کنید.\n"
        f"🚀 ربات به‌طور خودکار بهترین کیفیت را دانلود می‌کند."
    )
    bot.reply_to(message, welcome, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin_panel_command(message):
    user_id = message.from_user.id
    if str(user_id) not in [str(uid) for uid in ADMIN_IDS]:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel_from_main")
def admin_panel_from_main_callback(call):
    user_id = call.from_user.id
    if str(user_id) not in [str(uid) for uid in ADMIN_IDS]:
        bot.answer_callback_query(call.id, "⛔ فقط ادمین", show_alert=True)
        return
    show_admin_panel(call.message.chat.id)

# ================= بقیه کالبک‌های ادمین (با استفاده از show_admin_panel) =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    user_id = call.from_user.id
    if str(user_id) not in [str(uid) for uid in ADMIN_IDS]:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید!", show_alert=True)
        return

    if call.data == "admin_stats":
        today = datetime.now().strftime("%Y%m%d")
        active = sum(1 for u in users_data.values() if u.get("last_date") == today)
        downloads = sum(u.get("daily_count", 0) for u in users_data.values() if u.get("last_date") == today)
        text = f"📊 **آمار امروز**\n👥 کاربران فعال: {active}\n📥 دانلودها: {downloads}"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "admin_settings":
        text = f"⚙️ **تنظیمات ربات**\nمحدودیت عادی: {DAILY_LIMIT_NORMAL}\nمحدودیت VIP: {DAILY_LIMIT_VIP}\nحذف فایل بعد: {settings.get('delete_seconds', FILE_DELETE_SECONDS)} ثانیه\nحداکثر حجم: {settings.get('max_size_mb', 500)} MB"
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
        settings["delete_seconds"] = settings.get("delete_seconds", FILE_DELETE_SECONDS) + 5
        save_json(SETTINGS_FILE, settings)
        bot.answer_callback_query(call.id, f"زمان حذف: {settings['delete_seconds']} ثانیه")
        show_admin_panel(call.message.chat.id)

    elif call.data == "admin_dec_del":
        if settings.get("delete_seconds", FILE_DELETE_SECONDS) > 5:
            settings["delete_seconds"] -= 5
            save_json(SETTINGS_FILE, settings)
            bot.answer_callback_query(call.id, f"زمان حذف: {settings['delete_seconds']} ثانیه")
        else:
            bot.answer_callback_query(call.id, "حداقل ۵ ثانیه!", show_alert=True)
        show_admin_panel(call.message.chat.id)

    elif call.data == "admin_inc_size":
        settings["max_size_mb"] = min(2000, settings.get("max_size_mb", 500) + 50)
        save_json(SETTINGS_FILE, settings)
        bot.answer_callback_query(call.id, f"حداکثر حجم: {settings['max_size_mb']}MB")
        show_admin_panel(call.message.chat.id)

    elif call.data == "admin_dec_size":
        if settings.get("max_size_mb", 500) > 50:
            settings["max_size_mb"] -= 50
            save_json(SETTINGS_FILE, settings)
            bot.answer_callback_query(call.id, f"حداکثر حجم: {settings['max_size_mb']}MB")
        else:
            bot.answer_callback_query(call.id, "حداقل ۵۰MB!", show_alert=True)
        show_admin_panel(call.message.chat.id)

    elif call.data == "admin_users":
        users_list = "\n".join([f"`{uid}` - {'VIP' if u['tier']=='vip' else 'عادی'} - {'🚫' if u.get('banned') else '✅'}" for uid, u in list(users_data.items())[:20]])
        text = f"📋 **کاربران (۲۰ نفر اول)**\n{users_list}"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

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
        show_admin_panel(call.message.chat.id)

    elif call.data == "admin_logs":
        log_text = "\n".join(admin_logs[-20:]) if admin_logs else "هیچ لاگی"
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back"))
        bot.edit_message_text(f"📜 **لاگ‌های ادمین** (۲۰ مورد آخر)\n{log_text}", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "admin_broadcast":
        msg = bot.send_message(call.message.chat.id, "📤 **پیام همگانی خود را وارد کنید:**")
        bot.register_next_step_handler(msg, broadcast_message, call.message)

    elif call.data == "admin_restart":
        bot.edit_message_text("🔄 در حال ریست...", call.message.chat.id, call.message.message_id)
        time.sleep(1)
        os._exit(0)

    elif call.data == "admin_back":
        show_admin_panel(call.message.chat.id)

# ================= توابع کمکی ادمین =================
def add_vip_step(message, orig_msg):
    if str(message.from_user.id) not in [str(uid) for uid in ADMIN_IDS]: return
    try:
        uid = int(message.text.strip())
        set_user_tier(uid, "vip")
        bot.send_message(message.chat.id, f"✅ کاربر {uid} VIP شد.")
        admin_logs.append(f"{datetime.now()} افزودن VIP به {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    show_admin_panel(orig_msg.chat.id)

def remove_vip_step(message, orig_msg):
    if str(message.from_user.id) not in [str(uid) for uid in ADMIN_IDS]: return
    try:
        uid = int(message.text.strip())
        set_user_tier(uid, "normal")
        bot.send_message(message.chat.id, f"✅ VIP کاربر {uid} حذف شد.")
        admin_logs.append(f"{datetime.now()} حذف VIP از {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    show_admin_panel(orig_msg.chat.id)

def ban_user_step(message, orig_msg):
    if str(message.from_user.id) not in [str(uid) for uid in ADMIN_IDS]: return
    try:
        uid = int(message.text.strip())
        set_banned(uid, True)
        bot.send_message(message.chat.id, f"🚫 کاربر {uid} بن شد.")
        admin_logs.append(f"{datetime.now()} بن کاربر {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    show_admin_panel(orig_msg.chat.id)

def unban_user_step(message, orig_msg):
    if str(message.from_user.id) not in [str(uid) for uid in ADMIN_IDS]: return
    try:
        uid = int(message.text.strip())
        set_banned(uid, False)
        bot.send_message(message.chat.id, f"✅ بن کاربر {uid} برداشته شد.")
        admin_logs.append(f"{datetime.now()} رفع بن {uid}")
    except:
        bot.send_message(message.chat.id, "❌ آیدی نامعتبر")
    show_admin_panel(orig_msg.chat.id)

def broadcast_message(message, orig_msg):
    if str(message.from_user.id) not in [str(uid) for uid in ADMIN_IDS]: return
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
    show_admin_panel(orig_msg.chat.id)

# ================= هندلر عضویت =================
@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def check_membership_callback(call):
    user_id = call.from_user.id
    if is_member(user_id):
        remaining = get_remaining_limit(user_id)
        tier = get_user_tier(user_id)
        welcome = (
            f"🎬 **ربات دانلود فوق‌پیشرفته ۲۰۲۶**\n\n"
            f"👑 سطح: {'VIP ⭐' if tier=='vip' else 'عادی'}\n"
            f"📊 دانلود باقی‌مانده امروز: `{remaining}`\n\n"
            f"✅ فقط کافیست لینک خود را ارسال کنید.\n"
            f"🚀 ربات به‌طور خودکار بهترین کیفیت را دانلود می‌کند."
        )
        bot.edit_message_text(welcome, call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "هنوز عضو نشده‌اید!", show_alert=True)

# ================= هندلر اصلی دانلود =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "⛔ شما مسدود هستید.")
        return
    if not is_member(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}"))
        markup.add(InlineKeyboardButton("✅ عضویت پیدا کردم", callback_data="check_membership"))
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
    status_msg = bot.reply_to(message, f"🔍 **پلتفرم:** {platform}\n⚡ شروع دانلود بهترین کیفیت...", parse_mode="Markdown")

    stop_event = threading.Event()
    cancel_events[user_id] = stop_event

    def process():
        with lock:
            active_downloads[user_id] = time.time()
        try:
            def progress_callback(msg):
                try:
                    bot.edit_message_text(msg, message.chat.id, status_msg.message_id, parse_mode="Markdown")
                except:
                    pass
            result = downloader.download(url, progress_callback)
            if result and os.path.exists(result['file']):
                file_size = result['size']
                max_size = settings.get('max_size_mb', 500) * 1024 * 1024
                if file_size > max_size:
                    bot.send_message(message.chat.id, f"❌ حجم فایل بیشتر از {settings['max_size_mb']}MB است!")
                    os.remove(result['file'])
                    return
                increment_daily_usage(user_id)
                remaining = get_remaining_limit(user_id)
                metadata = result.get('metadata', {})
                caption = f"✅ **دانلود شد!**\n📥 روش: {result['method']}\n📌 عنوان: {metadata.get('title', 'Unknown')}\n👤 آپلودر: {metadata.get('uploader', 'Unknown')}\n⏱️ مدت: {metadata.get('duration', 0)} ثانیه\n👍 لایک: {metadata.get('like_count', 0)}\n👁️ بازدید: {metadata.get('view_count', 0)}\n📊 حجم: {file_size/1024/1024:.1f}MB\n📊 باقی‌مانده امروز: {remaining}"
                with open(result['file'], 'rb') as f:
                    if result['type'] == 'audio':
                        bot.send_audio(message.chat.id, f, caption=caption)
                    else:
                        bot.send_video(message.chat.id, f, caption=caption)
                schedule_file_deletion(result['file'])
                try:
                    bot.edit_message_text("✅ ارسال شد!", message.chat.id, status_msg.message_id)
                except:
                    pass
            else:
                bot.send_message(message.chat.id, "❌ خطا در دانلود! همه روش‌ها ناموفق بودند.")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ خطا: {str(e)[:200]}")
        finally:
            with lock:
                if user_id in active_downloads:
                    del active_downloads[user_id]
            if user_id in cancel_events:
                del cancel_events[user_id]

    threading.Thread(target=process, daemon=True).start()

@bot.message_handler(commands=['cancel'])
def cancel_download(message):
    user_id = message.from_user.id
    if user_id in cancel_events:
        cancel_events[user_id].set()
        bot.reply_to(message, "⏹ درخواست لغو ثبت شد.")
    else:
        bot.reply_to(message, "ℹ️ هیچ دانلودی در حال انجام نیست.")

if __name__ == "__main__":
    print("🚀 ربات با حالت Polling راه‌اندازی شد")
    bot.remove_webhook()
    time.sleep(1)
    # حذف خطوط webhook و Flask
    print("✅ ربات در حال اجرا (Polling)...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
