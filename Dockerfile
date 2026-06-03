FROM python:3.11-slim

# 安装系统依赖和 FFmpeg（全功能版）
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制代码
COPY main.py /app/main.py

# 创建输出目录（用于生成 live.m3u）
RUN mkdir -p /www

# 安装 Python 依赖
RUN pip install --no-cache-dir requests

# 暴露端口（如果你想通过 HTTP 提供 m3u 文件）
EXPOSE 80

# 安装轻量级静态文件服务器（可选）
RUN pip install --no-cache-dir waitress

# 启动命令：先运行生成脚本，然后启动 HTTP 服务提供 m3u
CMD ["sh", "-c", "python /app/main.py && waitress-serve --port=80 --call 'main:serve_m3u'"]

# 如果你不想自动启动 HTTP 服务，只想生成文件，可以改成：
# CMD ["python", "/app/main.py"]
