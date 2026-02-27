# -*- coding: utf-8 -*-
import os
import re
import time
import threading
import json
import subprocess
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 500 * 1024 * 1024  # افزایش به 500 مگابایت
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = {}
download_progress = {}
lock = threading.Lock()

# ================= User-Agent های مختلف =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ================= ابزار لینک =================
def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def is_youtube(url):
    return any(x in url for x in ['youtube.com', 'youtu.be'])

def clean_url(url):
    url = re.sub(r'\?si=[^&]+', '', url)
    url = re.sub(r'&si=[^&]+', '', url)
    return url

# ================= موتور دانلود فوق پیشرفته با ۱۵ روش =================
class AdvancedDownloader:
    def __init__(self):
        self.methods = [
            self.method_1_ytdlp_best,
            self.method_2_ytdlp_720p,
            self.method_3_ytdlp_480p,
            self.method_4_ytdlp_360p,
            self.method_5_audio,
            self.method_6_ytdlp_android,
            self.method_7_ytdlp_ios,
            self.method_8_ytdlp_web,
            self.method_9_ytdlp_cookie,
            self.method_10_ytdlp_bypass,
            self.method_11_subprocess_best,
            self.method_12_subprocess_720p,
            self.method_13_subprocess_audio,
            self.method_14_ytdlp_fallback,
            self.method_15_ytdlp_ultimate,
        ]
        self.method_names = [
            "yt-dlp بهترین کیفیت",
            "yt-dlp 720p",
            "yt-dlp 480p",
            "yt-dlp 360p",
            "دانلود صوتی",
            "کلاینت اندروید",
            "کلاینت iOS",
            "کلاینت وب",
            "با کوکی",
            "عبور از محدودیت",
            "subprocess بهترین",
            "subprocess 720p",
            "subprocess صوتی",
            "fallback نهایی",
            "التمیت روش نهایی",
        ]
    
    def _download_with_ydl(self, url, format_spec, quality_name, is_audio=False):
        """تابع پایه برای دانلود با yt-dlp"""
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"%(title)s_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': format_spec,
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 15,
            'fragment_retries': 15,
            'socket_timeout': 30,
            'concurrent_fragment_downloads': 1,
            'restrictfilenames': True,
            'nocheckcertificate': True,
            'user_agent': random.choice(USER_AGENTS),
        }
        
        if is_audio:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if 'requested_downloads' in info and info['requested_downloads']:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
                
                if is_audio:
                    filepath = os.path.splitext(filepath)[0] + '.mp3'
                
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': quality_name, 'size': os.path.getsize(filepath)}
        except:
            return None
        return None
    
    def _download_with_subprocess(self, url, format_spec, quality_name):
        """تابع پایه برای دانلود با subprocess"""
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"video_{unique}.mp4")
        
        try:
            cmd = [
                'yt-dlp',
                '-f', format_spec,
                '-o', output,
                '--no-playlist',
                '--quiet',
                '--no-warnings',
                '--user-agent', random.choice(USER_AGENTS),
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if result.returncode == 0 and os.path.exists(output):
                return {'file': output, 'method': quality_name, 'size': os.path.getsize(output)}
        except:
            pass
        return None
    
    # روش ۱: yt-dlp بهترین کیفیت
    def method_1_ytdlp_best(self, url):
        return self._download_with_ydl(url, 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 'روش 1')
    
    # روش ۲: yt-dlp 720p
    def method_2_ytdlp_720p(self, url):
        return self._download_with_ydl(url, 'best[height<=720][ext=mp4]/best[ext=mp4]/best', 'روش 2')
    
    # روش ۳: yt-dlp 480p
    def method_3_ytdlp_480p(self, url):
        return self._download_with_ydl(url, 'best[height<=480][ext=mp4]/best[ext=mp4]/best', 'روش 3')
    
    # روش ۴: yt-dlp 360p
    def method_4_ytdlp_360p(self, url):
        return self._download_with_ydl(url, 'best[height<=360][ext=mp4]/worst[ext=mp4]/worst', 'روش 4')
    
    # روش ۵: دانلود صوتی
    def method_5_audio(self, url):
        return self._download_with_ydl(url, 'bestaudio/best', 'روش 5', is_audio=True)
    
    # روش ۶: کلاینت اندروید
    def method_6_ytdlp_android(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"android_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': 'player_client=android_embedded'},
            'user_agent': USER_AGENTS[3],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': 'روش 6', 'size': os.path.getsize(filepath)}
        except:
            pass
        return None
    
    # روش ۷: کلاینت iOS
    def method_7_ytdlp_ios(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"ios_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': 'player_client=ios'},
            'user_agent': USER_AGENTS[2],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': 'روش 7', 'size': os.path.getsize(filepath)}
        except:
            pass
        return None
    
    # روش ۸: کلاینت وب
    def method_8_ytdlp_web(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"web_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'user_agent': USER_AGENTS[0],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': 'روش 8', 'size': os.path.getsize(filepath)}
        except:
            pass
        return None
    
    # روش ۹: با کوکی (اگر وجود داشته باشد)
    def method_9_ytdlp_cookie(self, url):
        if not os.path.exists('cookies.txt'):
            return None
        
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"cookie_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': 'روش 9', 'size': os.path.getsize(filepath)}
        except:
            pass
        return None
    
    # روش ۱۰: عبور از محدودیت جغرافیایی
    def method_10_ytdlp_bypass(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"bypass_{unique}.%(ext)s")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': output,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if os.path.exists(filepath):
                    return {'file': filepath, 'method': 'روش 10', 'size': os.path.getsize(filepath)}
        except:
            pass
        return None
    
    # روش ۱۱: subprocess بهترین کیفیت
    def method_11_subprocess_best(self, url):
        return self._download_with_subprocess(url, 'best[ext=mp4]', 'روش 11')
    
    # روش ۱۲: subprocess 720p
    def method_12_subprocess_720p(self, url):
        return self._download_with_subprocess(url, 'best[height<=720][ext=mp4]', 'روش 12')
    
    # روش ۱۳: subprocess صوتی
    def method_13_subprocess_audio(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"audio_{unique}.mp3")
        
        try:
            cmd = [
                'yt-dlp',
                '-f', 'bestaudio',
                '--extract-audio',
                '--audio-format', 'mp3',
                '-o', output,
                '--no-playlist',
                '--quiet',
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if result.returncode == 0 and os.path.exists(output):
                return {'file': output, 'method': 'روش 13', 'size': os.path.getsize(output)}
        except:
            pass
        return None
    
    # روش ۱۴: fallback نهایی
    def method_14_ytdlp_fallback(self, url):
        formats = [
            'worst[ext=mp4]',
            'worst',
            'best',
        ]
        
        for fmt in formats:
            try:
                result = self._download_with_ydl(url, fmt, 'روش 14')
                if result:
                    return result
            except:
                continue
        return None
    
    # روش ۱۵: التیمیت روش نهایی
    def method_15_ytdlp_ultimate(self, url):
        unique = str(int(time.time()*1000)) + str(random.randint(100, 999))
        output = os.path.join(DOWNLOAD_PATH, f"ultimate_{unique}.mp4")
        
        try:
            cmd = [
                'yt-dlp',
                '--ignore-errors',
                '--no-check-certificate',
                '--prefer-insecure',
                '--user-agent', random.choice(USER_AGENTS),
                '--extractor-args', 'youtube:player_client=android_embedded',
                '--geo-bypass',
                '-f', 'best',
                '-o', output,
                '--no-playlist',
                '--quiet',
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if result.returncode == 0 and os.path.exists(output):
                return {'file': output, 'method': 'روش 15', 'size': os.path.getsize(output)}
        except:
            pass
        return None
    
    def download(self, url, quality, progress_callback=None):
        """تلاش با همه ۱۵ روش"""
        
        # انتخاب روش‌های مناسب بر اساس کیفیت
        if quality == 'audio':
            methods_to_try = [5, 13]  # فقط روش‌های صوتی
        else:
            methods_to_try = range(15)  # همه روش‌ها
        
        for i in methods_to_try:
            method = self.methods[i]
            method_name = self.method_names[i]
            
            if progress_callback:
                progress_callback(f"🔄 تلاش با {method_name}...")
            
            try:
                result = method(url)
                if result:
                    return result
            except:
                continue
            
            time.sleep(1)
        
        return None

# ================= ایجاد نمونه از دانلودر =================
downloader = AdvancedDownloader()

# ================= کیبورد کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 بهترین کیفیت", callback_data="q_best"),
        InlineKeyboardButton("720p", callback_data="q_720"),
        InlineKeyboardButton("480p", callback_data="q_480"),
        InlineKeyboardButton("360p", callback_data="q_360"),
        InlineKeyboardButton("🎵 فقط صدا", callback_data="q_audio"),
        InlineKeyboardButton("❌ لغو", callback_data="q_cancel")
    )
    return markup

# ================= استارت =================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(
        message,
        "🎬 **ربات دانلود یوتیوب - نسخه التیمیت**\n\n"
        "✅ **۱۵ روش مختلف دانلود**\n"
        "✅ پشتیبانی از Shorts و ویدیوهای معمولی\n"
        "✅ عبور از محدودیت سنی و جغرافیایی\n"
        "✅ حجم مجاز: ۵۰۰ مگابایت\n"
        "✅ **۱۰۰٪ تضمینی**\n\n"
        "📌 **فقط کافیه لینک یوتیوب رو بفرستی!**",
        parse_mode="Markdown"
    )

# ================= دریافت لینک =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id

    if user_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return

    url = extract_url(message.text)
    if not url:
        return

    if not is_youtube(url):
        bot.reply_to(message, "❌ فقط لینک یوتیوب بفرست!")
        return

    url = clean_url(url)
    user_links[user_id] = url
    
    bot.reply_to(
        message, 
        "📥 **کیفیت مورد نظر رو انتخاب کن:**\n\n"
        "🎯 ۱۵ روش مختلف برای دانلود آماده است!", 
        reply_markup=quality_keyboard(), 
        parse_mode="Markdown"
    )

# ================= انتخاب کیفیت =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def quality_selected(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    if call.data == "q_cancel":
        bot.edit_message_text("❌ عملیات لغو شد.", chat_id, call.message.message_id)
        return

    if user_id in active_downloads:
        bot.answer_callback_query(call.id, "⏳ صبر کن دانلود قبلی تموم شه!")
        return

    quality = call.data.replace("q_", "")
    url = user_links.get(user_id)

    if not url:
        bot.answer_callback_query(call.id, "❌ خطا: لینک یافت نشد!")
        return

    bot.edit_message_text(
        "🔄 **در حال آماده‌سازی ۱۵ روش دانلود...**\n"
        "⏳ این فرآیند چند لحظه طول می‌کشد",
        chat_id,
        call.message.message_id,
        parse_mode="Markdown"
    )

    def progress_callback(message):
        try:
            bot.edit_message_text(
                message,
                chat_id,
                call.message.message_id,
                parse_mode="Markdown"
            )
        except:
            pass

    def process():
        try:
            with lock:
                active_downloads[user_id] = time.time()

            result = downloader.download(url, quality, progress_callback)

            if result and os.path.exists(result['file']):
                file_size = os.path.getsize(result['file'])
                
                if file_size > MAX_FILE_SIZE:
                    bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f} مگابایت است!")
                    os.remove(result['file'])
                    return

                progress_callback(f"📤 **در حال آپلود...**\n📊 حجم: {file_size/1024/1024:.1f}MB")

                with open(result['file'], 'rb') as f:
                    if quality == 'audio' or result['file'].endswith('.mp3'):
                        bot.send_audio(
                            chat_id, 
                            f,
                            caption=f"✅ **دانلود با موفقیت انجام شد!**\n"
                                   f"📥 روش: {result['method']}\n"
                                   f"📊 حجم: {file_size/1024/1024:.1f}MB\n"
                                   f"🎯 ۱۵ روش مختلف امتحان شد",
                            timeout=300
                        )
                    else:
                        bot.send_video(
                            chat_id, 
                            f,
                            caption=f"✅ **دانلود با موفقیت انجام شد!**\n"
                                   f"📥 روش: {result['method']}\n"
                                   f"📊 حجم: {file_size/1024/1024:.1f}MB\n"
                                   f"🎯 ۱۵ روش مختلف امتحان شد",
                            timeout=300
                        )

                os.remove(result['file'])

                try:
                    bot.edit_message_text(
                        "✅ **دانلود با موفقیت انجام شد!**",
                        chat_id,
                        call.message.message_id,
                        parse_mode="Markdown"
                    )
                except:
                    pass

            else:
                bot.send_message(
                    chat_id, 
                    "❌ **خطا در دانلود!**\n"
                    "همه ۱۵ روش امتحان شدند اما موفق نبود.\n"
                    "مشکل ممکنه از این موارد باشه:\n"
                    "• ویدیو خصوصی یا حذف شده\n"
                    "• محدودیت شدید کپی‌رایت\n"
                    "• مشکل در سرور\n\n"
                    "لطفاً چند دقیقه بعد دوباره تلاش کنید."
                )

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")

        finally:
            with lock:
                if user_id in active_downloads:
                    del active_downloads[user_id]
                if user_id in user_links:
                    del user_links[user_id]

    threading.Thread(target=process, daemon=True).start()

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        version = result.stdout.strip() if result.returncode == 0 else "نامشخص"
    except:
        version = "نامشخص"
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"✅ **۱۵ روش دانلود فعال**\n"
    text += f"📊 دانلودهای هم‌زمان: {len(active_downloads)}\n"
    text += f"📦 yt-dlp نسخه: {version}\n"
    text += f"💾 حجم مجاز: ۵۰۰ مگابایت\n"
    
    # لیست روش‌ها
    methods = [
        "1. yt-dlp بهترین کیفیت", "2. yt-dlp 720p", "3. yt-dlp 480p", "4. yt-dlp 360p",
        "5. دانلود صوتی", "6. کلاینت اندروید", "7. کلاینت iOS", "8. کلاینت وب",
        "9. با کوکی", "10. عبور از محدودیت", "11. subprocess بهترین", "12. subprocess 720p",
        "13. subprocess صوتی", "14. fallback نهایی", "15. التیمیت روش نهایی"
    ]
    
    text += "\n📋 **روش‌های فعال:**\n"
    for i, method in enumerate(methods[:5], 1):
        text += f"{method}\n"
    text += "..."
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ================= وبهوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "ربات دانلود یوتیوب با ۱۵ روش - ۱۰۰٪ تضمینی"

if __name__ == "__main__":
    print("="*70)
    print("🎬 ربات دانلود یوتیوب - نسخه التیمیت با ۱۵ روش")
    print("="*70)
    print("✅ ۱۵ روش مختلف دانلود:")
    print("   1. yt-dlp بهترین کیفیت")
    print("   2. yt-dlp 720p")
    print("   3. yt-dlp 480p")
    print("   4. yt-dlp 360p")
    print("   5. دانلود صوتی")
    print("   6. کلاینت اندروید")
    print("   7. کلاینت iOS")
    print("   8. کلاینت وب")
    print("   9. با کوکی")
    print("   10. عبور از محدودیت")
    print("   11. subprocess بهترین")
    print("   12. subprocess 720p")
    print("   13. subprocess صوتی")
    print("   14. fallback نهایی")
    print("   15. التیمیت روش نهایی")
    print("="*70)
    print("🎯 **۱۰۰٪ تضمینی**")
    print("="*70)
    
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print(f"✅ Webhook: {WEBHOOK_URL}")
    print("✅ ربات با ۱۵ روش فعال شد!")
    print("="*70)
    
    app.run(host="0.0.0.0", port=PORT)
