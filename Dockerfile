FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install -U yt-dlp flask pyTelegramBotAPI requests gunicorn

WORKDIR /app
COPY . .

# نصب وابستگی‌ها
RUN pip install -r requirements.txt || true

# پورت مورد استفاده
EXPOSE 8080

CMD ["python", "bot.py"]
