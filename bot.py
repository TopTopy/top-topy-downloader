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

# ================= User-Agent های مختلف برای دور زدن 403 =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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

# ================= ابزار =================
def extract_urls(text):
    return re.findall(r'https?://[^\s]+', text)

def is_youtube_url(url):
    url = url.lower()
    youtube_domains = ['youtube.com', 'youtu.be']
    return any(domain in url for domain in youtube_domains)

# ================= دانلودر قدرتمند با قابلیت عبور از محدودیت‌ها =================
class YouTubeDownloader:
    def __init__(self):
        pass
    
    def get_video_info(self, url):
        """گرفتن اطلاعات ویدیو با روش‌های مختلف"""
        
        # روش 1: با User-Agent عادی
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
                    'age_limit': info.get('age_limit', 0),
                    'availability': 'available'
                }
        except:
            pass
        
        # روش 2: با کوکی (برای ویدیوهای سنی)
        cookies_file = "cookies.txt"
        if os.path.exists(cookies_file):
            try:
                cmd = [
                    'yt-dlp',
                    '--cookies', cookies_file,
                    '--dump-json',
                    '--no-playlist',
                    '--quiet',
                    '--user-agent', USER_AGENTS[1],
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
                        'age_limit': info.get('age_limit', 0),
                        'availability': 'available_with_cookie'
                    }
            except:
                pass
        
        # روش 3: با مرورگر (برای ویدیوهای خیلی محدود)
        try:
            cmd = [
                'yt-dlp',
                '--extractor-args', 'youtube:player_client=android_embedded',
                '--dump-json',
                '--no-playlist',
                '--quiet',
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
                    'age_limit': info.get('age_limit', 0),
                    'availability': 'available_with_mobile'
                }
        except:
            pass
        
        return None
    
    def download_with_bypass(self, url, quality, chat_id, msg_id):
        """دانلود با قابلیت عبور از تمام محدودیت‌ها"""
        
        # تنظیمات پایه
        base_cmd = [
            'yt-dlp',
            '--no-playlist',
            '--no-warnings',
            '--progress',
            '--newline',
        ]
        
        # اضافه کردن گزینه‌های مختلف برای عبور از محدودیت‌ها
        bypass_options = [
            [],  # روش عادی
            ['--user-agent', USER_AGENTS[2]],  # با User-Agent موبایل
            ['--extractor-args', 'youtube:player_client=android_embedded'],  # کلاینت اندروید
            ['--extractor-args', 'youtube:player_client=ios'],  # کلاینت iOS
            ['--extractor-args', 'youtube:skip=webpage'],  # رد کردن صفحه وب
            ['--geo-bypass'],  # عبور از محدودیت جغرافیایی
            ['--geo-bypass-country', 'US'],  # عبور با آی‌پی آمریکا
        ]
        
        # اگه فایل کوکی وجود داره، اضافه کن
        cookies_file = "cookies.txt"
        if os.path.exists(cookies_file):
            bypass_options.append(['--cookies', cookies_file])
        
        # تنظیم فرمت بر اساس کیفیت
        if quality == 'best':
            format_option = '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == '720p':
            format_option = '-f', 'best[height<=720][ext=mp4]/best[ext=mp4]/best'
        elif quality == '360p':
            format_option = '-f', 'best[height<=360][ext=mp4]/worst[ext=mp4]/worst'
        elif quality == 'audio':
            format_option = '-f', 'bestaudio'
        else:
            format_option = '-f', 'best[ext=mp4]/best'
        
        output_template = f'{DOWNLOAD_PATH}/%(title)s_%(id)s.%(ext)s'
        
        # امتحان همه روش‌ها
        for i, bypass in enumerate(bypass_options):
            try:
                if msg_id:
                    bot.edit_message_text(
                        f"🔄 **روش {i+1}/{len(bypass_options)} برای عبور از محدودیت...**",
                        chat_id,
                        msg_id,
                        parse_mode="Markdown"
                    )
                
                # ساخت دستور کامل
                cmd = base_cmd.copy()
                cmd.extend(bypass)
                cmd.extend([format_option[0], format_option[1]])
                cmd.extend(['-o', output_template])
                cmd.append(url)
                
                # اگه صوتی هست، گزینه‌های اضافه کن
                if quality == 'audio':
                    cmd.extend(['--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0'])
                
                # اجرای دانلود
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                         text=True, bufsize=1)
                
                for line in process.stdout:
                    if '%' in line:
                        try:
                            percent = re.search(r'(\d+\.\d+)%', line)
                            if percent:
                                prog = float(percent.group(1))
                                if msg_id and i == len(bypass_options)-1:  # فقط برای آخرین روش نشون بده
                                    bot.edit_message_text(
                                        f"📥 **در حال دانلود...**\n⏳ {prog:.1f}%",
                                        chat_id,
                                        msg_id,
                                        parse_mode="Markdown"
                                    )
                        except:
                            pass
                
                process.wait()
                
                if process.returncode == 0:
                    time.sleep(2)
                    files = os.listdir(DOWNLOAD_PATH)
                    latest_file = max(
                        [os.path.join(DOWNLOAD_PATH, f) for f in files],
                        key=os.path.getctime
                    )
                    return {
                        'filename': latest_file,
                        'size': os.path.getsize(latest_file),
                        'quality': quality,
                        'method': i+1
                    }
                    
            except Exception as e:
                print(f"خطا در روش {i+1}: {e}")
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

def get_error_message(error_text):
    """تشخیص نوع خطا و برگردوندن پیام مناسب"""
    if '403' in error_text or 'Forbidden' in error_text:
        return "🚫 **خطای 403 - دسترسی ممنوع**\nیوتیوب درخواست رو بلاک کرده. در حال تلاش با روش جایگزین..."
    elif 'Video unavailable' in error_text:
        return "❌ **ویدیو در دسترس نیست**\nاین ویدیو ممکنه حذف یا خصوصی شده باشه."
    elif 'Sign in' in error_text or 'age' in error_text.lower():
        return "🔞 **ویدیو محدودیت سنی دارد**\nبرای دانلود نیاز به حساب یوتیوب دارید."
    elif 'DRM' in error_text:
        return "🔒 **ویدیو دارای محافظت DRM است**\nاین ویدیو قابل دانلود نیست."
    else:
        return None

# ================= کیبورد انتخاب کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 بهترین کیفیت", callback_data="quality_best"),
        InlineKeyboardButton("🎥 720p", callback_data="quality_720p"),
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
        "✅ **قابلیت‌های ویژه:**\n"
        "• عبور از خطای 403 Forbidden\n"
        "• دانلود ویدیوهای محدودیت سنی\n"
        "• دور زدن محدودیت جغرافیایی\n"
        "• دانلود با ۶ روش مختلف\n"
        "• نمایش پیشرفت دانلود\n\n"
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
        f"🔄 **در حال آماده‌سازی روش‌های عبور از محدودیت...**",
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
        result = downloader.download_with_bypass(url, quality, chat_id, msg_id)
        
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
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {result['size']/1024/1024:.1f}MB\n🔄 روش: {result['method']}",
                        timeout=120
                    )
                else:
                    bot.send_video(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {result['size']/1024/1024:.1f}MB\n🔄 روش: {result['method']}",
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
                "❌ **خطا در دانلود!**\nهمه روش‌ها امتحان شدند اما موفق نبود.",
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
    except Exception as e:
        error_msg = get_error_message(str(e))
        if error_msg:
            bot.edit_message_text(
                error_msg,
                chat_id,
                msg_id,
                parse_mode="Markdown"
            )
        else:
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
        age_warning = ""
        if info.get('age_limit', 0) > 0:
            age_warning = "\n⚠️ **این ویدیو محدودیت سنی دارد**"
        
        info_text = (
            f"📹 **اطلاعات ویدیو**{age_warning}\n\n"
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
            "ممکنه ویدیو حذف شده یا خصوصی باشه.",
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
    return "ربات دانلود یوتیوب - عبور از تمام محدودیت‌ها"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود یوتیوب - عبور از تمام محدودیت‌ها")
    print("="*70)
    print(f"✅ yt-dlp: {'نصب است' if YT_DLP_OK else 'نصب نیست'}")
    print("✅ قابلیت‌های ویژه:")
    print("   • عبور از 403 Forbidden")
    print("   • دانلود ویدیوهای محدودیت سنی")
    print("   • دور زدن محدودیت جغرافیایی")
    print("   • ۶ روش مختلف دانلود")
    print("="*70)
    
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
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
