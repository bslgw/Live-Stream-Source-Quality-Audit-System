# 📡 直播源质量审计系统

文件说明

m3u_auto.py                主程序，运行后生成live.m3u，并上传cloudflare worker 

config.json                主程序参数配置文件

config_editor.py           可视化管理参数配置

auto_blacklist.json        死链黑名单

worker.js                  cloudflare托管m3u

upload.sh                  linux脚本，用于上传live.m3u到cloudflare worker 托管

使用 https://worker链接/live.m3u


下载 FFmpeg 6.1

```
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-6.1-amd64-static.tar.xz
```
```
tar -xf ffmpeg-6.1-amd64-static.tar.xz
```
```
cp ffmpeg-6.1-amd64-static/ffmpeg /root/ffmpeg
```
```
/root/ffmpeg -version
```
