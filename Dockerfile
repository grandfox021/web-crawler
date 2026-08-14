FROM python:3.11-slim

# جلوگیری از سوال‌های تعاملی apt و بافر شدن لاگ پایتون
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# نصب dependencyهای پایتون جدا از کد، برای cache بهتر
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نصب Chromium و لایبرری‌های سیستمی موردنیازش
RUN playwright install --with-deps chromium

# کپی کد پروژه
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]