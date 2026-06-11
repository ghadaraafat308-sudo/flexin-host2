FROM python:3.11-slim

# مجلد العمل
WORKDIR /app

# متغيرات لتحسين اللوجات
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# تثبيت المكتبات أولاً (لاستغلال الـ cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# تشغيل البوت
CMD ["python", "-u", "bot_v51_newkeys.py"]
