# -*- coding: utf-8 -*-
import os
import re
import time
import threading
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

# ================= تنظیمات =================
TOKEN = "8629099905:AAHy7-EcCBj2YyxbcjxfW91qRslQ-21311M"
ADMIN_ID = 8226091292
MAX_FILE_SIZE = 300 * 1024 * 1024  # افزایش به 300 مگابایت
DOWNLOAD_PATH = "downloads"
WEBHOOK_URL = "https://top-topy-downloader-production.up.railway.app/webhook"
PORT = int(os.environ.get("PORT", 8080))
REQUIRED_CHANNELS = [
    ("@top_topy_downloader", "https://t.me/top_topy_downloader"),
    ("@IdTOP_TOPY", "https://t.me/IdTOP_TOPY")
]

os.makedirs(DOWNLOAD_PATH, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_links = {}
active_downloads = set()
lock = threading.Lock()

# ================= ابزار لینک =================
def extract_url(text):
    urls = re.findall(r'https?://\S+', text)
    return urls[0] if urls else None

def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url

def check_membership(user_id):
    """بررسی عضویت کاربر در کانال‌های اجباری"""
    try:
        for username, _ in REQUIRED_CHANNELS:
            member = bot.get_chat_member(username, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except:
        return False

def force_join_markup():
    """کیبورد عضویت اجباری"""
    markup = InlineKeyboardMarkup(row_width=1)
    for name, link in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 عضویت در {name}", url=link))
    markup.add(InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return markup

# ================= دانلود حرفه‌ای =================
def download_video(url, quality):

    unique = str(int(time.time()*1000))
    output = f"{DOWNLOAD_PATH}/%(title)s_{unique}.%(ext)s"

    # مهم: fallback format گذاشتیم
    format_map = {
        "best": "bestvideo+bestaudio/best",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "360": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        "audio": "bestaudio"
    }

    ydl_opts = {
        "format": format_map.get(quality, "best"),
        "outtmpl": output,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "retries": 5,
        "fragment_retries": 5,
    }

    if quality == "audio":
        ydl_opts.update({
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            # گرفتن اسم فایل نهایی درست
            if "requested_downloads" in info:
                filename = info["requested_downloads"][0]["filepath"]
            else:
                filename = ydl.prepare_filename(info)

            if quality == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"

            if os.path.exists(filename):
                return filename

    except Exception as e:
        print("Download Error:", e)

    return None

# ================= کیبورد کیفیت =================
def quality_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎥 بهترین", callback_data="q_best"),
        InlineKeyboardButton("720p", callback_data="q_720"),
        InlineKeyboardButton("480p", callback_data="q_480"),
        InlineKeyboardButton("360p", callback_data="q_360"),
        InlineKeyboardButton("🎵 صدا", callback_data="q_audio"),
        InlineKeyboardButton("❌ لغو", callback_data="q_cancel")
    )
    return markup

# ================= استارت =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    
    if not check_membership(user_id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    bot.reply_to(
        message,
        "🎬 **ربات دانلود یوتیوب**\n\n"
        "✅ لینک یوتیوب رو بفرست تا برات دانلود کنم!\n"
        "✅ پشتیبانی از Shorts\n"
        "✅ حجم مجاز: ۳۰۰ مگابایت",
        parse_mode="Markdown"
    )

# ================= پنل ادمین =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ دسترسی ندارید!")
        return
    
    # بررسی نسخه yt-dlp
    try:
        import subprocess
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        version = result.stdout.strip() if result.returncode == 0 else "نامشخص"
    except:
        version = "نامشخص"
    
    text = f"👑 **پنل مدیریت**\n\n"
    text += f"✅ ربات فعال است\n"
    text += f"📊 دانلودهای هم‌زمان: {len(active_downloads)}\n"
    text += f"📦 yt-dlp نسخه: {version}\n"
    text += f"👤 ادمین: {ADMIN_ID}"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ================= بررسی عضویت =================
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if check_membership(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ عضویت تأیید شد!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ عضو نشده‌اید!", show_alert=True)

# ================= دریافت لینک =================
@bot.message_handler(content_types=['text'])
def handle(message):
    user_id = message.from_user.id
    
    # بررسی عضویت
    if not check_membership(user_id):
        bot.reply_to(
            message,
            "🔒 **برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:**",
            reply_markup=force_join_markup(),
            parse_mode="Markdown"
        )
        return

    if user_id in active_downloads:
        bot.reply_to(message, "⏳ یک دانلود در حال انجام است... لطفاً صبر کنید.")
        return

    url = extract_url(message.text)
    if not url:
        return

    if not is_youtube(url):
        bot.reply_to(message, "❌ فقط لینک یوتیوب بفرست!")
        return

    user_links[user_id] = url
    bot.reply_to(
        message, 
        "📥 **کیفیت مورد نظر رو انتخاب کن:**", 
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

    bot.edit_message_text("⏳ **در حال دانلود...**", chat_id, call.message.message_id, parse_mode="Markdown")

    def process():
        try:
            with lock:
                active_downloads.add(user_id)

            file_path = download_video(url, quality)

            if not file_path or not os.path.exists(file_path):
                bot.send_message(chat_id, "❌ خطا در دانلود! لطفاً دوباره تلاش کنید.")
                return

            file_size = os.path.getsize(file_path)
            if file_size > MAX_FILE_SIZE:
                bot.send_message(chat_id, f"❌ حجم فایل بیشتر از {MAX_FILE_SIZE/1024/1024:.0f} مگابایت است!")
                os.remove(file_path)
                return

            # ارسال فایل
            with open(file_path, "rb") as f:
                if quality == "audio" or file_path.endswith('.mp3'):
                    bot.send_audio(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {file_size/1024/1024:.1f}MB",
                        timeout=180
                    )
                else:
                    bot.send_video(
                        chat_id, 
                        f,
                        caption=f"✅ **دانلود کامل شد**\n📊 حجم: {file_size/1024/1024:.1f}MB",
                        timeout=180
                    )

            # پاک کردن فایل
            os.remove(file_path)
            
            # ویرایش پیام وضعیت
            try:
                bot.edit_message_text(
                    "✅ **دانلود با موفقیت انجام شد!**",
                    chat_id,
                    call.message.message_id,
                    parse_mode="Markdown"
                )
            except:
                pass

        except Exception as e:
            bot.send_message(chat_id, f"❌ خطا:\n{str(e)[:200]}")

        finally:
            with lock:
                active_downloads.discard(user_id)
            if user_id in user_links:
                del user_links[user_id]

    threading.Thread(target=process).start()

# ================= وبهوک =================
@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "ربات دانلود یوتیوب فعال است"

if __name__ == "__main__":
    print("="*60)
    print("🎬 ربات دانلود یوتیوب")
    print("="*60)
    print(f"✅ توکن: {TOKEN[:10]}...")
    print(f"✅ ادمین: {ADMIN_ID}")
    print(f"✅ وبهوک: {WEBHOOK_URL}")
    print("="*60)
    
    # پاکسازی فایل‌های قدیمی
    for f in os.listdir(DOWNLOAD_PATH):
        try:
            os.remove(os.path.join(DOWNLOAD_PATH, f))
        except:
            pass
    
    # تنظیم وبهوک
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL)
    
    print("✅ ربات فعال شد!")
    print("="*60)
    
    app.run(host="0.0.0.0", port=PORT)
