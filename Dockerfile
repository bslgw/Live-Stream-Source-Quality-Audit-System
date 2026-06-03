FROM python:3.11-slim

# 安装完整版 FFmpeg（Debian 源，功能最全）
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制你的主脚本
COPY main.py /app/main.py

# 确保输出目录存在（映射到宿主机 /www）
RUN mkdir -p /www

# 安装 Python 依赖
RUN pip install --no-cache-dir requests

# 权限设置（OpenWRT www 目录通常是 www-data 或 root）
RUN chmod -R 755 /www

# 启动命令：运行生成脚本（生成到 /www/live.m3u）
CMD ["python", "/app/main.py"]
