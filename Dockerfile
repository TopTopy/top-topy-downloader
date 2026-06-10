FROM python:3.11-slim

# نصب ffmpeg و ابزارهای مورد نیاز
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# نصب yt-dlp و کتابخانه‌های پایتون
RUN pip install --upgrade pip
RUN pip install yt-dlp flask pyTelegramBotAPI requests

# آپدیت yt-dlp به آخرین نسخه
RUN pip install -U yt-dlp

# بررسی نصب ffmpeg
RUN ffmpeg -version || echo "FFmpeg installed"

WORKDIR /app
COPY . .

# نصب وابستگی‌های پایتون از requirements.txt (اگه وجود داشته باشه)
RUN pip install -r requirements.txt || true

CMD ["python", "bot.py"]
