
FROM 192.168.13.79:5052/python3.13.15-playwright:v1 


# جلوگیری از سوال‌های تعاملی apt و بافر شدن لاگ پایتون
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app


RUN dpkg -l | grep tzdata || apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*

# نصب dependencyهای پایتون جدا از کد، برای cache بهتر
COPY requirements.txt .
RUN pip install -r requirements.txt

# نصب Chromium و لایبرری‌های سیستمی موردنیازش
#RUN playwright install --with-deps chromium

# کپی کد پروژه
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]