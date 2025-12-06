# Use lightweight Python image
FROM python:3.9-slim

# ปิด progress bar + ปิด version check กันปัญหา rich/thread
ENV PIP_PROGRESS_BAR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# ตัดการ upgrade pip ออก และลง dependencies แบบเรียบง่าย
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Command to run the bot
CMD ["python", "main_bot.py"]
