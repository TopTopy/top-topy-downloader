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

# ================= User-Agent های مختلف =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

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

# ================= ابزار قوی برای استخراج لینک =================
def extract_urls(text):
    """استخراج همه لینک‌ها از متن با پشتیبانی از لینک‌های کوتاه"""
    # پترن قوی برای تشخیص لینک
    url_pattern = r'https?://[^\s<>"\'(){}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    
    # پاکسازی لینک‌ها از کاراکترهای اضافی
    cleaned_urls = []
    for url in urls:
        # حذف کاراکترهای اضافی از انتهای لینک
        url = re.sub(r'[.,;:!?()\[\]]+$', '', url)
        cleaned_urls.append(url)
    
    return cleaned_urls

def is_youtube_url(url):
    """بررسی اینکه آیا لینک یوتیوب است"""
    url = url.lower()
    youtube_domains = ['youtube.com', 'youtu.be', 'm.youtube.com', 'youtube.com/shorts']
    return any(domain in url for domain in youtube_domains)

def clean_url(url):
    """پاکسازی و نرمال‌سازی لینک"""
    # حذف پارامترهای اضافی
    url = re.sub(r'&si=[^&]+', '', url)
    url = re.sub(r'\?si=[^&]+', '', url)
    return url

# ================= دانلودر قدرتمند =================
class YouTubeDownloader:
    def __init__(self):
        pass
    
    def get_video_info(self, url):
        """گرفتن اطلاعات ویدیو"""
        try:
            cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                '--user-agent', USER_AGENTS[0],
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                info = json.loads(result.stdout)
                return {
                    'title': info.get('title', 'بدون عنوان'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'ناشناس'),
                    'views': info.get('view_count', 0),
                }
            else:
                # تلاش با روش دوم
                cmd = [
                    'yt-dlp',
                    '--extractor-args', 'youtube:player_client=android_embedded',
                    '--dump-json',
                    '--no-playlist',
                    '--quiet',
                    '--user-agent', USER_AGENTS[2],
                    url
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    return {
                        'title': info.get('title', 'بدون عنوان'),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', 'ناشناس'),
                        'views': info.get('view_count', 0),
                    }
        except:
            pass
        
        return None
    
    def download_video(self, url, quality, chat_id, msg_id):
        """دانلود ویدیو"""
        
        # تنظیم فرمت بر اساس کیفیت
        format_map = {
            'best': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '720p': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
            '480p': 'best[height<=480][ext=mp4]/best[ext=mp4]/best',
            '360p': 'best[height<=360][ext=mp4]/worst[ext=mp4]/worst',
            'audio': 'bestaudio'
        }
        format_option = format_map.get(quality, 'best[ext=mp4]/best')
        
        output_template = f'{DOWNLOAD_PATH}/%(title)s_%(id)s.%(ext)s'
        
        # ساخت دستور پایه
        base_cmd = [
            'yt-dlp',
            '-f', format_option,
            '-o', output_template,
            '--no-playlist',
            '--no-warnings',
            '--progress',
            '--newline',
        ]
        
        # اگر کیفیت صوتی هست
        if quality == 'audio':
            base_cmd.extend(['--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0'])
        
        # ۵ روش مختلف
        methods = [
            {'name': 'معمولی', 'cmd': base_cmd + ['--user-agent', USER_AGENTS[0], url]},
            {'name': 'موبایل', 'cmd': base_cmd + ['--user-agent', USER_AGENTS[2], '--extractor-args', 'youtube:player_client=android_embedded', url]},
            {'name': 'عبور از تحریم', 'cmd': base_cmd + ['--geo-bypass', '--geo-bypass-country', 'US', url]},
            {'name': 'مخصوص Shorts', 'cmd': base_cmd + ['--user-agent', USER_AGENTS[3], '--extractor-args', 'youtube:player_client=android_embedded', url.replace('shorts/', 'watch?v=')]},
            {'name': 'تلاش مجدد', 'cmd': base_cmd + ['--retries', '10', '--fragment-retries', '10', url]}
        ]
        
        for i, method in enumerate(methods, 1):
            try:
                if msg_id:
                    bot.edit_message_text(
                        f"🔄 **روش {i}/5**\n📡 {method['name']}...",
                        chat_id,
                        msg_id,
                        parse_mode="Markdown"
                    )
                
                process = subprocess.Popen(
                    method['cmd'], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True, 
                    bufsize=1
                )
                
                for line in process.stdout:
                    if '%' in line and msg_id:
                        percent_match = re.search(r'(\d+\.\d+)%', line)
                        if percent_match:
                            percent = float(percent_match.group(1))
                            if percent % 10 < 1:  # هر ۱۰٪ آپدیت کن
                                bot.edit_message_text(
                                    f"📥 **{method['name']}**\n⏳ {percent:.1f}%",
                                    chat_id,
                                    msg_id,
                                    parse_mode="Markdown"
                                )
                
                process.wait()
                
                if process.returncode == 0:
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
                            'quality': quality,
                            'method': method['name']
                        }
                
            except Exception as e:
                print(f"خطا در روش {i}: {e}")
                continue
        
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
        "• دانلود با ۵ روش مختلف\n"
        "• پشتیبانی از Shorts\n"
        "• نمایش پیشرفت دانلود\n"
        "• کیفیت‌های مختلف\n\n"
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
    
    # استخراج لینک با روش قوی‌تر
    text = call.message.text
    urls = extract_urls(text)
    
    if not urls:
        bot.edit_message_text(
            "❌ **خطا: لینک یافت نشد!**\nلطفاً دوباره لینک رو ارسال کنید.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        return
    
    url = clean_url(urls[0])
    
    bot.edit_message_text(
        f"🔄 **در حال آماده‌سازی ۵ روش دانلود...**",
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
            if result['size'] > MAX_FILE_SIZE:
                os.remove(result['filename'])
                bot.edit_message_text(
                    "❌ **حجم فایل بیشتر از ۳۰۰ مگابایت است**",
                    chat_id,
                    msg_id,
                    parse_mode="Markdown"
                )
                return
            
            with open(result['filename'], 'rb') as f:
                if quality == 'audio' or result['filename'].endswith('.mp3'):
                    bot.send_audio(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📥 روش: {result['method']}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=180
                    )
                else:
                    bot.send_video(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📥 روش: {result['method']}\n📊 حجم: {result['size']/1024/1024:.1f}MB",
                        timeout=180
                    )
            
            os.remove(result['filename'])
            db.add_download(user_id)
            
            bot.edit_message_text(
                f"✅ **دانلود با موفقیت انجام شد!**",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                "❌ **خطا در دانلود!**\nهمه روش‌ها امتحان شدند اما موفق نبود.",
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
    if not message.text:
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

    # استخراج لینک با روش قوی
    urls = extract_urls(message.text)
    if not urls:
        return
    
    url = clean_url(urls[0])
    
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
            "❌ **yt-dlp روی سرور نصب نیست!**",
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
            "❌ **خطا در دریافت اطلاعات ویدیو!**",
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
    text += f"🟢 وضعیت: فعال"
    
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
    print("✅ ۵ روش دانلود")
    print("="*60)
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات فعال شد!")
    print("="*60)
    
    app.run(host="0.0.0.0", port=PORT)
