#!/bin/sh
# upload live.m3u 到 Cloudflare Worker

FILE="/root/live.m3u"

if [ ! -f "$FILE" ]; then
    echo "文件不存在: $FILE"
    exit 1
fi

echo "上传 live.m3u ..."

# 使用 curl 上传
/usr/bin/curl -s -L -X POST --data-binary @"$FILE" "https://m3u.bbsok.cc.cd/upload?name=live.m3u"

echo
echo "上传完成"
echo "访问地址:"
echo "https://m3u.bbsok.cc.cd/f/live.m3u"