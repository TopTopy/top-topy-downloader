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
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
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

def clean_filename(filename):
    """پاکسازی نام فایل از کاراکترهای ممنوع"""
    return re.sub(r'[\\/*?:"<>|]', '', filename)

# ================= دانلودر قدرتمند =================
class YouTubeDownloader:
    def __init__(self):
        pass
    
    def get_video_info(self, url):
        """گرفتن اطلاعات ویدیو با ۳ روش مختلف"""
        
        # روش‌های مختلف برای دریافت اطلاعات
        methods = [
            # روش 1: معمولی
            [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                '--user-agent', USER_AGENTS[0],
                url
            ],
            # روش 2: با کلاینت موبایل
            [
                'yt-dlp',
                '--extractor-args', 'youtube:player_client=android_embedded',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                '--user-agent', USER_AGENTS[2],
                url
            ],
            # روش 3: با آی‌پی مجازی
            [
                'yt-dlp',
                '--geo-bypass',
                '--geo-bypass-country', 'US',
                '--dump-json',
                '--no-playlist',
                '--quiet',
                url
            ]
        ]
        
        for i, cmd in enumerate(methods):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    return {
                        'title': info.get('title', 'بدون عنوان'),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', 'ناشناس'),
                        'views': info.get('view_count', 0),
                        'age_limit': info.get('age_limit', 0),
                        'success_method': i+1
                    }
            except:
                continue
        
        return None
    
    def download_video(self, url, quality, chat_id, msg_id):
        """دانلود ویدیو با ۱۰ روش مختلف برای عبور از همه محدودیت‌ها"""
        
        # تنظیم فرمت بر اساس کیفیت
        if quality == 'best':
            format_option = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif quality == '720p':
            format_option = 'best[height<=720][ext=mp4]/best[ext=mp4]/best'
        elif quality == '480p':
            format_option = 'best[height<=480][ext=mp4]/best[ext=mp4]/best'
        elif quality == '360p':
            format_option = 'best[height<=360][ext=mp4]/worst[ext=mp4]/worst'
        elif quality == 'audio':
            format_option = 'bestaudio'
        else:
            format_option = 'best[ext=mp4]/best'
        
        # نام فایل خروجی
        output_template = f'{DOWNLOAD_PATH}/%(title)s_%(id)s.%(ext)s'
        
        # ۱۰ روش مختلف برای دانلود
        download_methods = [
            # روش 1: معمولی
            {
                'name': 'معمولی',
                'cmd': [
                    'yt-dlp',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[0],
                    url
                ]
            },
            # روش 2: با کلاینت اندروید
            {
                'name': 'کلاینت اندروید',
                'cmd': [
                    'yt-dlp',
                    '--extractor-args', 'youtube:player_client=android_embedded',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[3],
                    url
                ]
            },
            # روش 3: با کلاینت iOS
            {
                'name': 'کلاینت iOS',
                'cmd': [
                    'yt-dlp',
                    '--extractor-args', 'youtube:player_client=ios',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[2],
                    url
                ]
            },
            # روش 4: با عبور از محدودیت جغرافیایی
            {
                'name': 'عبور از تحریم',
                'cmd': [
                    'yt-dlp',
                    '--geo-bypass',
                    '--geo-bypass-country', 'US',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    url
                ]
            },
            # روش 5: با کیفیت پایین (برای ویدیوهای سنگین)
            {
                'name': 'کیفیت تطبیقی',
                'cmd': [
                    'yt-dlp',
                    '-f', 'best[ext=mp4]/worst[ext=mp4]',
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[1],
                    url
                ]
            },
            # روش 6: با هدرهای مختلف
            {
                'name': 'هدر موبایل',
                'cmd': [
                    'yt-dlp',
                    '--add-header', 'Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    '--add-header', 'Accept-Language', 'en-us,en;q=0.5',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[2],
                    url
                ]
            },
            # روش 7: با تلاش مجدد
            {
                'name': 'تلاش مجدد',
                'cmd': [
                    'yt-dlp',
                    '--retries', '10',
                    '--fragment-retries', '10',
                    '--file-access-retries', '10',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    url
                ]
            },
            # روش 8: با کوکی (اگه فایل وجود داشته باشه)
            {
                'name': 'با کوکی',
                'cmd': [
                    'yt-dlp',
                    '--cookies', 'cookies.txt' if os.path.exists('cookies.txt') else '/dev/null',
                    '-f', format_option,
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    url
                ]
            },
            # روش 9: برای ویدیوهای کوتاه (Shorts)
            {
                'name': 'Shorts مخصوص',
                'cmd': [
                    'yt-dlp',
                    '--extractor-args', 'youtube:player_client=android_embedded',
                    '-f', 'best',
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    '--user-agent', USER_AGENTS[3],
                    url.replace('shorts/', 'watch?v=')
                ]
            },
            # روش 10: آخرین راهکار
            {
                'name': 'آخرین راهکار',
                'cmd': [
                    'yt-dlp',
                    '--ignore-errors',
                    '--no-check-certificate',
                    '--prefer-insecure',
                    '-f', 'worst',
                    '-o', output_template,
                    '--no-playlist',
                    '--no-warnings',
                    '--progress',
                    '--newline',
                    url
                ]
            }
        ]
        
        # اگر کیفیت صوتی هست، گزینه‌های اضافه کن
        if quality == 'audio':
            for method in download_methods:
                method['cmd'].extend(['--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0'])
        
        # امتحان همه روش‌ها
        for i, method in enumerate(download_methods, 1):
            try:
                if msg_id:
                    bot.edit_message_text(
                        f"🔄 **روش {i}/10**\n📡 {method['name']}...",
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
                
                last_percent = 0
                for line in process.stdout:
                    # نمایش پیشرفت
                    percent_match = re.search(r'(\d+\.\d+)%', line)
                    if percent_match:
                        percent = float(percent_match.group(1))
                        if percent - last_percent >= 5:  # هر ۵٪ آپدیت کن
                            last_percent = percent
                            if msg_id:
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
                            'method': f"{method['name']} (روش {i})"
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
        "✅ **قابلیت‌های ویژه:**\n"
        "• دانلود با ۱۰ روش مختلف\n"
        "• پشتیبانی از ویدیوهای Shorts\n"
        "• عبور از خطای 403\n"
        "• دور زدن محدودیت سنی\n"
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
    # استخراج لینک از متن پیام
    text = call.message.text
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        bot.edit_message_text("❌ خطا: لینک یافت نشد!", call.message.chat.id, call.message.message_id)
        return
    
    url = url_match.group(0)
    
    bot.edit_message_text(
        f"🔄 **در حال آماده‌سازی ۱۰ روش دانلود...**",
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
                "❌ **خطا در دانلود!**\nهمه ۱۰ روش امتحان شدند اما موفق نبود.",
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
            "ویدیو ممکنه حذف شده یا خصوصی باشه.",
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
    return "ربات دانلود یوتیوب با ۱۰ روش"

# ================= اجرا =================
if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود یوتیوب با ۱۰ روش")
    print("="*70)
    print(f"✅ yt-dlp: {'نصب است' if YT_DLP_OK else 'نصب نیست'}")
    print("✅ ۱۰ روش دانلود:")
    print("   1. معمولی")
    print("   2. کلاینت اندروید")
    print("   3. کلاینت iOS")
    print("   4. عبور از تحریم")
    print("   5. کیفیت تطبیقی")
    print("   6. هدر موبایل")
    print("   7. تلاش مجدد")
    print("   8. با کوکی")
    print("   9. مخصوص Shorts")
    print("   10. آخرین راهکار")
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
    print("✅ ربات با ۱۰ روش فعال شد!")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
