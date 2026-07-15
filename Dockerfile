FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Устанавливаем ffmpeg для сжатия видео (опционально)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Создаём не-root пользователя
RUN useradd -m -u 1000 botuser && \
    mkdir -p /tmp /app/data /app/downloads && \
    chown -R botuser:botuser /tmp /app/data /app/downloads

WORKDIR /app

# Копируем requirements
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Переключаемся на не-root пользователя
USER botuser

# Временная директория и постоянные данные
VOLUME ["/tmp", "/app/data", "/app/downloads"]

# Запуск
CMD ["python", "-m", "src.bot"]
