FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# 容器内固定监听 8000；宿主端口由 Compose 的 API_PORT 映射。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
