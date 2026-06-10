FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install -U yt-dlp flask pyTelegramBotAPI requests

WORKDIR /app
COPY . .

CMD ["python", "bot.py"]
