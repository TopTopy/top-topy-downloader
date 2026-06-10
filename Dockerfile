FROM python:3.11-slim

WORKDIR /app

# نصب ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# کپی فایل requirements و نصب
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کل کد
COPY . .

# پورت
EXPOSE 8080

# اجرا
CMD ["python", "bot.py"]
