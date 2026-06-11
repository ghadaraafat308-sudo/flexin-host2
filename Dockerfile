FROM python:3.11-slim

# مجلد العمل
WORKDIR /app

# متغيرات لتحسين اللوجات
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# تثبيت خطوط عربية + متطلبات النظام لـ Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core \
    fonts-noto-cjk \
    fonts-dejavu \
    libfreetype6 \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# تثبيت المكتبات أولاً (لاستغلال الـ cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# تشغيل البوت
CMD ["python", "-u", "bot_v51_newkeys.py"]
