# -*- coding: utf-8 -*-
import os
import threading
import time
import re
import subprocess
import json
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
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

# ================= بررسی نصب yt-dlp =================
def check_yt_dlp():
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ yt-dlp نسخه {result.stdout.strip()} نصب است")
            return True
        else:
            print("❌ yt-dlp نصب نیست")
            return False
    except:
        print("❌ yt-dlp نصب نیست")
        return False

YT_DLP_OK = check_yt_dlp()

# ================= ابزار =================
def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def is_youtube_url(url):
    url = url.lower()
    youtube_domains = ['youtube.com', 'youtu.be', 'm.youtube.com']
    return any(domain in url for domain in youtube_domains)

# ================= دانلودر ساده =================
class YouTubeDownloader:
    def __init__(self):
        pass
    
    def get_video_info(self, url):
        """گرفتن اطلاعات ویدیو با روش‌های مختلف"""
        
        # روش 1: ساده
        try:
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                '--no-warnings',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout:
                info = json.loads(result.stdout)
                return {
                    'title': info.get('title', 'بدون عنوان'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'ناشناس'),
                    'views': info.get('view_count', 0),
                    'success': True
                }
        except:
            pass
        
        # روش 2: با کلاینت موبایل
        try:
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                '--no-warnings',
                '--extractor-args', 'youtube:player_client=android_embedded',
                url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout:
                info = json.loads(result.stdout)
                return {
                    'title': info.get('title', 'بدون عنوان'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'ناشناس'),
                    'views': info.get('view_count', 0),
                    'success': True
                }
        except:
            pass
        
        return None
    
    def download_video(self, url, quality, chat_id, msg_id):
        """دانلود ویدیو"""
        try:
            # تنظیم فرمت
            if quality == 'best':
                format_option = 'best[ext=mp4]/best'
            elif quality == '720p':
                format_option = 'best[height<=720][ext=mp4]/best[ext=mp4]'
            elif quality == '480p':
                format_option = 'best[height<=480][ext=mp4]/best[ext=mp4]'
            elif quality == '360p':
                format_option = 'best[height<=360][ext=mp4]/best[ext=mp4]'
            elif quality == 'audio':
                format_option = 'bestaudio'
            else:
                format_option = 'best[ext=mp4]/best'
            
            output_template = f'{DOWNLOAD_PATH}/%(title)s.%(ext)s'
            
            # ساخت دستور
            cmd = [
                'yt-dlp',
                '-f', format_option,
                '-o', output_template,
                '--no-playlist',
                '--no-warnings',
                '--quiet',
                url
            ]
            
            # اگه صوتی هست
            if quality == 'audio':
                cmd.extend(['--extract-audio', '--audio-format', 'mp3'])
            
            # اجرای دانلود
            if msg_id:
                bot.edit_message_text(
                    "🔄 **در حال دانلود...**",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                time.sleep(2)
                files = os.listdir(DOWNLOAD_PATH)
                if files:
                    latest_file = max(
                        [os.path.join(DOWNLOAD_PATH, f) for f in files],
                        key=os.path.getctime
                    )
                    return {
                        'filename': latest_file,
                        'size': os.path.getsize(latest_file),
                        'quality': quality
                    }
            return None
            
        except subprocess.TimeoutExpired:
            if msg_id:
                bot.edit_message_text(
                    "⏱ **زمان دانلود بیش از حد طول کشید**\nلطفاً دوباره تلاش کنید.",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
            return None
        except Exception as e:
            print(f"خطا در دانلود: {e}")
            return None

# ================= ایجاد نمونه =================
downloader = YouTubeDownloader()

# ================= دیتابیس =================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("database/bot.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()

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
        self.cursor.execute("INSERT OR IGNORE INTO users(user_id,is_admin) VALUES(?,1)", (ADMIN_ID,))
        self.conn.commit()

    def add_user(self, user_id, username, first_name):
        now = datetime.now()
        self.cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        if self.cursor.fetchone():
            self.cursor.execute("UPDATE users SET last_use=? WHERE user_id=?", (now, user_id))
        else:
            self.cursor.execute("INSERT INTO users(user_id,username,first_name,joined_date,last_use) VALUES(?,?,?,?,?)",
                              (user_id, username, first_name, now, now))
        self.conn.commit()

    def add_download(self, user_id):
        self.cursor.execute("UPDATE users SET download_count=download_count+1 WHERE user_id=?", (user_id,))
        self.conn.commit()

    def check_membership(self, user_id):
        try:
            for username, _ in REQUIRED_CHANNELS:
                member = bot.get_chat_member(username, user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    return False
            return True
        except:
            return False

    def is_blocked(self, user_id):
        self.cursor.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,))
        r = self.cursor.fetchone()
        return r and r[0] == 1

# ================= ربات =================
db = Database()
bot = telebot.TeleBot(TOKEN)

# ================= توابع کمکی =================
def force_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

def format_duration(seconds):
    minutes = seconds // 60
    hours = minutes // 60
    if hours > 0:
        return f"{hours}:{minutes%60:02d}:{seconds%60:02d}"
    else:
        return f"{minutes}:{seconds%60:02d}"

# ================= کیبورد انتخاب کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 بهترین کیفیت", callback_data="quality_best"),
        InlineKeyboardButton("🎥 720p", callback_data="quality_720p"),
        InlineKeyboardButton("🎥 480p", callback_data="quality_480p"),
        InlineKeyboardButton("🎥 360p", callback_data="quality_360p"),
        InlineKeyboardButton("🎵 فقط صدا", callback_data="quality_audio"),
        InlineKeyboardButton("❌ لغو", callback_data="quality_cancel")
    )
    return markup

# ================= هندلرها =================
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
        f"🎬 **سلام {message.from_user.first_name or message.from_user.username}!**\n\n"
        "به **ربات دانلود یوتیوب** خوش اومدی 🤖\n\n"
        "✅ **قابلیت‌ها:**\n"
        "• دانلود با کیفیت‌های مختلف\n"
        "• دانلود صوتی MP3\n"
        "• پشتیبانی از لینک‌های کوتاه\n"
        "• حجم تا ۳۰۰ مگابایت\n\n"
        "📌 **فقط کافیه لینک یوتیوب رو بفرستی!**"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if db.check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ عضو نشده‌اید!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quality_'))
def quality_callback(call):
    if call.data == "quality_cancel":
        bot.edit_message_text("❌ عملیات لغو شد.", call.message.chat.id, call.message.message_id)
        return
    
    quality = call.data.replace('quality_', '')
    url = call.message.text.split('\n')[-1]
    
    bot.edit_message_text(
        f"🔄 **در حال دانلود...**\n⏳ لطفاً صبر کنید",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    threading.Thread(
        target=process_download,
        args=(url, quality, call.message.chat.id, call.from_user.id, call.message.message_id),
        daemon=True
    ).start()

def process_download(url, quality, chat_id, user_id, msg_id):
    try:
        result = downloader.download_video(url, quality, chat_id, msg_id)
        
        if result:
            # بررسی حجم فایل
            if result['size'] > MAX_FILE_SIZE:
                os.remove(result['filename'])
                bot.edit_message_text(
                    "❌ **حجم فایل بیشتر از ۳۰۰ مگابایت است**",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
                return
            
            # ارسال فایل
            with open(result['filename'], 'rb') as f:
                if quality == 'audio' or result['filename'].endswith('.mp3'):
                    bot.send_audio(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=120
                    )
                else:
                    bot.send_video(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=120
                    )
            
            # پاک کردن فایل
            os.remove(result['filename'])
            
            # آپدیت دیتابیس
            db.add_download(user_id)
            
            # ویرایش پیام
            bot.edit_message_text(
                f"✅ **دانلود با موفقیت انجام شد!**",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                "❌ **خطا در دانلود!**\nلطفاً دوباره تلاش کنید.",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
    except Exception as e:
        bot.edit_message_text(
            f"❌ **خطا:**\n`{str(e)[:200]}`",
            chat_id,
            msg_id,
            parse_mode="Markdown"
        )

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_message(message):
    if not message.text.startswith(('http://', 'https://')):
        return

    if db.is_blocked(message.from_user.id):
        bot.reply_to(message, "⛔ شما بلاک هستید")
        return

    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    if not db.check_membership(message.from_user.id):
        bot.reply_to(
            message,
            "🔒 **لطفاً ابتدا در کانال‌ها عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    urls = extract_urls(message.text)
    if not urls:
        return
    
    url = urls[0]
    
    if not is_youtube_url(url):
        bot.reply_to(
            message,
            "❌ **لطفاً فقط لینک یوتیوب ارسال کنید**",
            parse_mode="Markdown"
        )
        return
    
    if not YT_DLP_OK:
        bot.reply_to(
            message,
            "❌ **yt-dlp روی سرور نصب نیست!**\nلطفاً به ادمین اطلاع دهید.",
            parse_mode="Markdown"
        )
        return
    
    # دریافت اطلاعات ویدیو
    info_msg = bot.reply_to(message, "🔄 **در حال دریافت اطلاعات...**", parse_mode="Markdown")
    
    info = downloader.get_video_info(url)
    
    if info:
        info_text = (
            f"📹 **اطلاعات ویدیو**\n\n"
            f"📌 عنوان: `{info['title'][:50]}...`\n"
            f"⏱ مدت: {format_duration(info['duration'])}\n"
            f"👤 کانال: {info['uploader']}\n"
            f"👁 بازدید: {info['views']:,}\n\n"
            f"⬇️ **کیفیت مورد نظر را انتخاب کنید:**"
        )
        
        bot.edit_message_text(
            info_text,
            info_msg.chat.id,
            info_msg.message_id,
            reply_markup=quality_keyboard(),
            parse_mode="Markdown"
        )
    else:
        bot.edit_message_text(
            "❌ **خطا در دریافت اطلاعات ویدیو!**\n"
            "ممکنه لینک اشتباه باشه یا ویدیو حذف شده باشه.\n"
            "لطفاً لینک رو دوباره بررسی کنید.",
            info_msg.chat.id,
            info_msg.message_id,
            parse_mode="Markdown"
        )

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    stats = db.cursor.execute("SELECT COUNT(*), SUM(download_count) FROM users").fetchone()
    total_users = stats[0] or 0
    total_downloads = stats[1] or 0
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"👥 کاربران: {total_users}\n"
    text += f"📥 دانلودها: {total_downloads}\n"
    text += f"🟢 yt-dlp: {'نصب است' if YT_DLP_OK else 'نصب نیست'}\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

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
    return "ربات دانلود یوتیوب"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود یوتیوب")
    print("="*60)
    print(f"✅ yt-dlp: {'نصب است' if YT_DLP_OK else 'نصب نیست'}")
    print("✅ کیفیت‌ها: Best, 720p, 480p, 360p, MP3")
    print("✅ حجم مجاز: 300MB")
    print("="*60)
    
    # پاکسازی فایل‌های قدیمی
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except:
            pass
    
    # تنظیم وب‌هوک
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات فعال شد!")
    print("="*60)
    
    app.run(host="0.0.0.0", port=PORT)
