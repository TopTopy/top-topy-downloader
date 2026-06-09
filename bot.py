# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import json
import subprocess
import random
import shutil
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
WEBHOOK_URL = "https://web-production-d8a05.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = {}
user_stats = {}  # آمار کاربران
group_settings = {}  # تنظیمات گروه‌ها
lock = threading.Lock()

# ================= تنظیم Webhook =================
def setup_webhook():
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"✅ Webhook set to: {WEBHOOK_URL}")
        return True
    except Exception as e:
        print(f"❌ Failed to set webhook: {e}")
        return False

setup_webhook()

# ================= تشخیص خودکار نوع محتوا =================
def detect_content_type(url):
    """تشخیص خودکار: video, music, image"""
    url_lower = url.lower()
    
    # تصویر
    image_exts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
    for ext in image_exts:
        if ext in url_lower:
            return 'image'
    
    # پلتفرم‌های موسیقی
    music_domains = ['soundcloud.com', 'spotify.com', 'deezer.com', 'music.youtube.com']
    for domain in music_domains:
        if domain in url_lower:
            return 'music'
    
    # بررسی با yt-dlp
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get('duration', 0)
            title = info.get('title', '').lower()
            
            # کمتر از 10 دقیقه و کلمات موسیقی
            if duration and duration < 600:
                music_keywords = ['music', 'song', 'audio', 'official audio', 'lyrics', 'آهنگ', 'موزیک']
                if any(kw in title for kw in music_keywords):
                    return 'music'
            return 'video'
    except:
        return 'video'

def get_content_emoji(content_type):
    emojis = {'video': '🎬', 'music': '🎵', 'image': '🖼️'}
    return emojis.get(content_type, '📹')

# ================= دانلود از پینترست (بر اساس پروژه ourpin) =================
class PinterestDownloader:
    @staticmethod
    def extract_pin_id(url):
        """استخراج ID پین از لینک"""
        patterns = [
            r'pinterest\.com/pin/(\d+)',
            r'pin\.it/([a-zA-Z0-9]+)',
            r'pinterest\.com/pin/\d+/(\d+)',
            r'pinterest\.com/pin/(\d+)/',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    @staticmethod
    def get_pin_data(pin_id):
        """دریافت اطلاعات پین از API پینترست"""
        try:
            # استفاده از API رسمی پینترست
            api_url = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9'
            }
            
            response = requests.get(api_url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('data') and len(data['data']) > 0:
                    return data['data'][0]
            return None
        except Exception as e:
            print(f"Pinterest API error: {e}")
            return None
    
    @staticmethod
    def download_image(url, filename):
        """دانلود تصویر"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except Exception as e:
            print(f"Image download error: {e}")
            return False
    
    @staticmethod
    def download_video(url, filename):
        """دانلود ویدیو"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except Exception as e:
            print(f"Video download error: {e}")
            return False
    
    @staticmethod
    def download_from_pinterest(url):
        """دانلود محتوا از پینترست"""
        try:
            pin_id = PinterestDownloader.extract_pin_id(url)
            if not pin_id:
                print(f"Could not extract pin ID from: {url}")
                return None
            
            pin_data = PinterestDownloader.get_pin_data(pin_id)
            if not pin_data:
                return None
            
            unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
            
            # بررسی ویدیو
            if pin_data.get('video') and pin_data['video'].get('video_url'):
                video_url = pin_data['video']['video_url']
                filepath = os.path.join(DOWNLOAD_PATH, f"pinterest_video_{unique}.mp4")
                
                if PinterestDownloader.download_video(video_url, filepath):
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 10240:
                        return {'file': filepath, 'method': 'پینترست (ویدیو)', 'type': 'video'}
                    else:
                        os.remove(filepath)
            
            # بررسی تصویر
            if pin_data.get('image'):
                # اولویت: original_url > large_url > small_url
                img_url = None
                if pin_data['image'].get('original_url'):
                    img_url = pin_data['image']['original_url']
                elif pin_data['image'].get('large_url'):
                    img_url = pin_data['image']['large_url']
                elif pin_data['image'].get('small_url'):
                    img_url = pin_data['image']['small_url']
                
                if img_url:
                    filepath = os.path.join(DOWNLOAD_PATH, f"pinterest_image_{unique}.jpg")
                    if PinterestDownloader.download_image(img_url, filepath):
                        if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                            return {'file': filepath, 'method': 'پینترست (تصویر)', 'type': 'image'}
            
            return None
        except Exception as e:
            print(f"Pinterest download error: {e}")
            return None

# ================= دانلود از یوتیوب (بر اساس پروژه telegram_youtube_downloader) =================
class YouTubeDownloader:
    @staticmethod
    def download(url, content_type='video'):
        """دانلود از یوتیوب با کیفیت مناسب"""
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        
        if content_type == 'music':
            # دانلود فقط صدا (مشابه پروژه)
            output = os.path.join(DOWNLOAD_PATH, f"youtube_music_{unique}.%(ext)s")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'extract_flat': False,
            }
        else:
            # دانلود ویدیو با بهترین کیفیت (مشابه پروژه)
            output = os.path.join(DOWNLOAD_PATH, f"youtube_video_{unique}.%(ext)s")
            ydl_opts = {
                'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                'outtmpl': output,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'merge_output_format': 'mp4',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'extract_flat': False,
            }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                
                if content_type == 'music':
                    filepath = os.path.splitext(filepath)[0] + '.mp3'
                
                # اگر فایل با پسوند دیگری ذخیره شده
                if not os.path.exists(filepath):
                    for f in os.listdir(DOWNLOAD_PATH):
                        if f.startswith(f"youtube_{content_type}_{unique}") or f.startswith(f"youtube_video_{unique}"):
                            filepath = os.path.join(DOWNLOAD_PATH, f)
                            break
                
                if os.path.exists(filepath) and os.path.getsize(filepath) > 10240:
                    media_type = 'music' if content_type == 'music' else 'video'
                    return {'file': filepath, 'method': 'یوتیوب دانلودر', 'type': media_type}
        except Exception as e:
            print(f"YouTube download error: {e}")
            return None
        return None

# ================= User-Agent ها =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
]

# ================= تشخیص پلتفرم =================
def detect_platform(url):
    url = url.lower()
    if 'youtube.com' in url or 'youtu.be' in url:
        return 'YouTube'
    if 'pinterest.com' in url or 'pin.it' in url:
        return 'Pinterest'
    if 'instagram.com' in url:
        return 'Instagram'
    if 'tiktok.com' in url:
        return 'TikTok'
    if 'twitter.com' in url or 'x.com' in url:
        return 'Twitter'
    if 'spotify.com' in url:
        return 'Spotify'
    if 'soundcloud.com' in url:
        return 'SoundCloud'
    return 'Other'

def extract_url(text):
    urls = re.findall(r'https?://[^\s]+', text)
    return urls[0] if urls else None

# ================= آمار و پنل ادمین =================
def update_stats(user_id, media_type, is_group=False):
    """به‌روزرسانی آمار"""
    key = f"group_{user_id}" if is_group else user_id
    if key not in user_stats:
        user_stats[key] = {'total': 0, 'video': 0, 'music': 0, 'image': 0}
    user_stats[key]['total'] += 1
    user_stats[key][media_type] = user_stats[key].get(media_type, 0) + 1

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    # آمار کلی
    total_users = len([k for k in user_stats if not str(k).startswith('group_')])
    total_groups = len([k for k in user_stats if str(k).startswith('group_')])
    total_downloads = sum(u['total'] for u in user_stats.values())
    total_video = sum(u.get('video', 0) for u in user_stats.values())
    total_music = sum(u.get('music', 0) for u in user_stats.values())
    total_image = sum(u.get('image', 0) for u in user_stats.values())
    
    text = f"👑 **پنل مدیریت ربات**\n\n"
    text += f"📊 **آمار کلی:**\n"
    text += f"├ 👤 کاربران: {total_users}\n"
    text += f"├ 👥 گروه‌ها: {total_groups}\n"
    text += f"├ 📥 دانلودها: {total_downloads}\n"
    text += f"├ 🎬 ویدیو: {total_video}\n"
    text += f"├ 🎵 موسیقی: {total_music}\n"
    text += f"└ 🖼️ تصویر: {total_image}\n\n"
    text += f"⚙️ **وضعیت:**\n"
    text += f"├ 🟢 ربات فعال\n"
    text += f"├ 📍 پلتفرم‌ها: YouTube, Pinterest, IG, TikTok\n"
    text += f"├ 💾 حجم مجاز: ۵۰۰ مگابایت\n"
    text += f"└ 🚀 دانلودر پیشرفته\n\n"
    text += f"📌 **دستورات ادمین:**\n"
    text += f"├ /stats - آمار دقیق\n"
    text += f"├ /broadcast - ارسال همگانی\n"
    text += f"├ /clean - پاک کردن کش\n"
    text += f"└ /groups - لیست گروه‌ها"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 آمار دقیق", callback_data="admin_stats"),
        InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin_broadcast"),
        InlineKeyboardButton("🗑️ پاک کردن کش", callback_data="admin_clean"),
        InlineKeyboardButton("👥 لیست گروه‌ها", callback_data="admin_groups")
    )
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ دسترسی ندارید!")
        return
    
    if call.data == "admin_stats":
        text = "📊 **آمار دقیق کاربران:**\n\n"
        count = 0
        for uid, stats in user_stats.items():
            if count >= 20:
                break
            if not str(uid).startswith('group_'):
                try:
                    user = bot.get_chat(int(uid))
                    name = user.first_name or str(uid)
                    text += f"├ 👤 {name[:20]}: {stats['total']} دانلود\n"
                    count += 1
                except:
                    text += f"├ 🆔 {uid}: {stats['total']} دانلود\n"
                    count += 1
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    
    elif call.data == "admin_clean":
        try:
            for f in os.listdir(DOWNLOAD_PATH):
                fpath = os.path.join(DOWNLOAD_PATH, f)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            bot.answer_callback_query(call.id, "✅ فایل‌های موقت پاک شد!")
            bot.edit_message_text("✅ **پاکسازی انجام شد!**\nفایل‌های موقت حذف گردید.", call.message.chat.id, call.message.message_id)
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطا: {e}")
    
    elif call.data == "admin_groups":
        text = "👥 **لیست گروه‌ها:**\n\n"
        count = 0
        for gid, stats in user_stats.items():
            if count >= 20:
                break
            if str(gid).startswith('group_'):
                try:
                    gid_clean = int(gid.replace('group_', ''))
                    chat = bot.get_chat(gid_clean)
                    name = chat.title or str(gid_clean)
                    text += f"├ 👥 {name[:25]}: {stats['total']} دانلود\n"
                    count += 1
                except:
                    text += f"├ 🆔 {gid}: {stats['total']} دانلود\n"
                    count += 1
        if count == 0:
            text += "└ ❌ هنوز گروهی ثبت نشده است."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ================= پیام خوشامدگویی =================
@bot.message_handler(commands=['start'])
def start(message):
    welcome_text = (
        "🎬 **ربات دانلود هوشمند - نسخه پیشرفته**\n\n"
        "✅ **تشخیص خودکار فیلم / آهنگ / تصویر**\n"
        "✅ **پشتیبانی از:**\n"
        "   ├ یوتیوب (با بهترین کیفیت)\n"
        "   ├ پینترست (ویدیو و تصویر)\n"
        "   ├ اینستاگرام | تیک‌تاک | توییتر\n"
        "   └ آپارات | اسپاتیفای | ساوندکلاود\n"
        "✅ **قابلیت کار در گروه‌ها**\n"
        "✅ **حجم مجاز: ۵۰۰ مگابایت**\n\n"
        "📌 **فقط کافیه لینک رو بفرستی!**\n"
        "ربات خودش تشخیص میده چی هست و بهترین روش رو انتخاب میکنه.\n\n"
        "🔹 **برای استفاده در گروه:**\n"
        "   - ربات رو به گروه اضافه کنید\n"
        "   - هر لینکی بفرستید، ربات پاسخ میده"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# ================= پشتیبانی از گروه =================
@bot.message_handler(commands=['settings'])
def group_settings_command(message):
    """تنظیمات گروه (فقط برای ادمین گروه)"""
    if message.chat.type in ['group', 'supergroup']:
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        # بررسی ادمین بودن کاربر در گروه
        try:
            chat_member = bot.get_chat_member(chat_id, user_id)
            if chat_member.status not in ['administrator', 'creator']:
                bot.reply_to(message, "❌ فقط ادمین گروه می‌تواند تنظیمات را تغییر دهد!")
                return
        except:
            bot.reply_to(message, "❌ خطا در بررسی دسترسی!")
            return
        
        current = group_settings.get(chat_id, {'auto_detect': True})
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(f"{'✅' if current.get('auto_detect', True) else '❌'} تشخیص خودکار", callback_data=f"group_setting_auto_{chat_id}"),
            InlineKeyboardButton("❌ خروج از تنظیمات", callback_data=f"group_setting_exit_{chat_id}")
        )
        
        bot.reply_to(message, "⚙️ **تنظیمات گروه:**\n\nتشخیص خودکار: به این معنی که ربات به همه لینک‌ها پاسخ می‌دهد.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_setting_'))
def group_setting_callback(call):
    data_parts = call.data.split('_')
    action = data_parts[2]
    chat_id = int(data_parts[3])
    
    if call.from_user.id != ADMIN_ID and call.message.chat.id == chat_id:
        # بررسی ادمین بودن در گروه
        try:
            chat_member = bot.get_chat_member(chat_id, call.from_user.id)
            if chat_member.status not in ['administrator', 'creator']:
                bot.answer_callback_query(call.id, "❌ فقط ادمین گروه می‌تواند تنظیمات را تغییر دهد!")
                return
        except:
            bot.answer_callback_query(call.id, "❌ خطا!")
            return
    
    if action == 'auto':
        current = group_settings.get(chat_id, {'auto_detect': True})
        current['auto_detect'] = not current.get('auto_detect', True)
        group_settings[chat_id] = current
        
        status = "فعال" if current['auto_detect'] else "غیرفعال"
        bot.answer_callback_query(call.id, f"✅ تشخیص خودکار {status} شد!")
        
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, f"⚙️ تشخیص خودکار هم‌اکنون **{status}** است.")
    
    elif action == 'exit':
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(call.message.chat.id, "✅ از تنظیمات خارج شدید.")

# ================= دریافت لینک (پیوی و گروه) =================
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_group = message.chat.type in ['group', 'supergroup']
    
    # بررسی تنظیمات گروه
    if is_group:
        settings = group_settings.get(chat_id, {'auto_detect': True})
        if not settings.get('auto_detect', True):
            return  # اگر تشخیص خودکار خاموش باشه، پاسخ نده
    
    # جلوگیری از پاسخ به دستورات
    if message.text.startswith('/'):
        return
    
    url = extract_url(message.text)
    if not url:
        if not is_group:
            bot.reply_to(message, "❌ لطفاً یک لینک معتبر بفرستید.")
        return
    
    # جلوگیری از دانلود همزمان برای یک کاربر/گروه
    check_id = f"group_{chat_id}" if is_group else user_id
    if check_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return
    
    platform = detect_platform(url)
    
    # پیام اولیه
    msg_text = f"🔍 **در حال بررسی لینک...**\n📱 پلتفرم: {platform}"
    if is_group:
        msg_text += f"\n👥 کاربر: {message.from_user.first_name}"
    
    msg = bot.reply_to(message, msg_text)
    
    # تشخیص خودکار نوع محتوا
    content_type = detect_content_type(url)
    content_emoji = get_content_emoji(content_type)
    content_name = {'video': 'ویدیو', 'music': 'آهنگ', 'image': 'تصویر'}.get(content_type, 'فایل')
    
    bot.edit_message_text(
        f"{content_emoji} **نوع محتوا تشخیص داده شد: {content_name}**\n\n"
        f"🔄 در حال دانلود با بهترین روش...",
        chat_id,
        msg.message_id
    )
    
    def process():
        try:
            with lock:
                active_downloads[check_id] = time.time()
            
            result = None
            
            # دانلود بر اساس پلتفرم
            if 'pinterest.com' in url or 'pin.it' in url:
                result = PinterestDownloader.download_from_pinterest(url)
            elif 'youtube.com' in url or 'youtu.be' in url:
                result = YouTubeDownloader.download(url, content_type)
            else:
                # سایر پلتفرم‌ها با yt-dlp مستقیم
                result = universal_download(url, content_type)
            
            if result and os.path.exists(result['file']):
                file_size = os.path.getsize(result['file'])
                
                if file_size > MAX_FILE_SIZE:
                    bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f} مگابایت است!")
                    os.remove(result['file'])
                    return
                
                # به‌روزرسانی آمار
                update_stats(user_id, result['type'], is_group)
                if is_group:
                    update_stats(f"group_{chat_id}", result['type'], True)
                
                caption = f"✅ **{content_name} با موفقیت دانلود شد!**\n"
                caption += f"📥 روش: {result['method']}\n"
                caption += f"📊 حجم: {file_size/1024/1024:.1f}MB"
                if is_group:
                    caption += f"\n👤 درخواست از: {message.from_user.first_name}"
                
                with open(result['file'], 'rb') as f:
                    if result['type'] == 'image':
                        bot.send_photo(chat_id, f, caption=caption)
                    elif result['type'] == 'music':
                        bot.send_audio(chat_id, f, caption=caption)
                    else:
                        bot.send_video(chat_id, f, caption=caption)
                
                os.remove(result['file'])
                
                try:
                    bot.edit_message_text("✅ **دانلود با موفقیت انجام شد!**", chat_id, msg.message_id)
                except:
                    pass
            else:
                bot.send_message(chat_id, "❌ **خطا در دانلود!**\nهمه روش‌ها امتحان شدند اما موفق نبودند.\nلطفاً لینک را بررسی کنید.")
        
        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")
        
        finally:
            with lock:
                if check_id in active_downloads:
                    del active_downloads[check_id]
    
    threading.Thread(target=process, daemon=True).start()

def universal_download(url, content_type='video'):
    """دانلود برای سایر پلتفرم‌ها"""
    unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
    
    if content_type == 'music':
        output = os.path.join(DOWNLOAD_PATH, f"download_audio_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        }
    else:
        output = os.path.join(DOWNLOAD_PATH, f"download_video_{unique}.%(ext)s")
        ydl_opts = {
            'format': 'best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
        }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if content_type == 'music':
                filepath = os.path.splitext(filepath)[0] + '.mp3'
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 10240:
                return {'file': filepath, 'method': 'دانلود خودکار', 'type': content_type}
    except:
        pass
    return None

# ================= دستورات ادمین اضافی =================
@bot.message_handler(commands=['stats'])
def stats_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    total_downloads = sum(u['total'] for u in user_stats.values())
    bot.reply_to(message, f"📊 **آمار:**\nدانلود کل: {total_downloads}\nکاربران: {len(user_stats)}")

@bot.message_handler(commands=['clean'])
def clean_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        for f in os.listdir(DOWNLOAD_PATH):
            fpath = os.path.join(DOWNLOAD_PATH, f)
            if os.path.isfile(fpath):
                os.remove(fpath)
        bot.reply_to(message, "✅ فایل‌های موقت پاک شد!")
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {e}")

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace('/broadcast', '').strip()
    if not text:
        bot.reply_to(message, "❌ لطفاً پیام را بعد از دستور بنویسید.\nمثال: /broadcast سلام!")
        return
    
    sent = 0
    for uid in user_stats:
        if not str(uid).startswith('group_'):
            try:
                bot.send_message(int(uid), f"📢 **پیام همگانی:**\n\n{text}", parse_mode="Markdown")
                sent += 1
                time.sleep(0.5)
            except:
                pass
    
    bot.reply_to(message, f"✅ پیام به {sent} کاربر ارسال شد.")

# ================= وب‌هوک =================
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook endpoint is active", 200
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Error: {e}")
        return "OK", 200

@app.route("/")
def home():
    return "ربات دانلود هوشمند - فعال است"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود هوشمند - نسخه نهایی")
    print("✅ تشخیص خودکار فیلم/آهنگ/تصویر")
    print("✅ پشتیبانی از یوتیوب و پینترست")
    print("✅ پشتیبانی کامل از گروه‌ها")
    print("✅ پنل ادمین کامل")
    print("="*60)
    
    if os.environ.get('RUNNING_LOCAL'):
        app.run(host="0.0.0.0", port=PORT)
