# Use lightweight Python image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables (can be overridden at runtime)
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "main_bot.py"]
