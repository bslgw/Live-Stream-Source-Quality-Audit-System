#!/usr/bin/env python3
"""
港台直播源质量审计调试工具
用于单链接深度诊断，输出每一步的详细处理过程和判定结果
"""

import requests
import re
import time
import subprocess
import socket
import json
from urllib.parse import urlparse

# ==================== 港台组专用配置 ====================
HKTW_CONFIG = {
    "timeout_video": 75,
    "timeout_stable": 25,
    "connect_timeout_basic": 40,
    "read_timeout_basic": 40,
    "min_speed_dead": 15360,          # 15KB/s 生死线
    "max_jitter_dead": 10.0,          # 10秒最大抖动
    "min_speed_normal": 18432,        # 18KB/s 正常速度
    "max_jitter_normal": 20.0,        # 20秒正常抖动
    "min_height": 288,                # 288p最低分辨率
    "min_speed_ratio": 0.08,          # 0.08x最低解码速率
    "connect_timeout_stable": 15,
    "allow_low_ratio": True,
    "strict_zombie_check": False,
    "strict_frame_check": False,
    "max_black_border": 60,
    "min_speed_4k": 100000,           # 4K最低速度100KB/s
    "max_jitter_4k": 6.5
}

# 播放器请求头
PLAYER_HEADERS = {
    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
    'Accept': '*/*',
    'Connection': 'close'
}

# 港台频道识别关键词
HK_TW_BRANDS = [
    "凤凰", "鳳凰", "TVB", "翡翠台", "翡翠臺", "明珠台", "明珠臺", 
    "东森", "東森", "中天", "纬来", "緯來", "三立", "八大", "年代", 
    "非凡", "华视", "華視", "台视", "臺視", "民视", "民視", 
    "公视", "公視", "中视", "中視", "TVBS", "靖天", "靖洋", 
    "寰宇", "美亚", "美亞", "影迷数位", "影迷數位", "AMC", 
    "香港卫视", "香港衛視", "HBO", "AXN", "FOX", "DISCOVERY", 
    "国家地理", "动物星球", "VIUTV", "HOY TV"
]

# 本地知名港台频道列表
LOCAL_HKTW_CHANNELS = [
    "中天新闻", "中天综合", "中天亚洲", "凤凰资讯", "凤凰卫视", 
    "凤凰中文", "凤凰香港", "TVBS新闻", "TVBS欢乐台", "TVBS", 
    "东森新闻", "东森电影", "东森综合", "东森洋片", "东森戏剧", 
    "东森幼幼", "纬来日本", "纬来体育", "纬来电影", "纬来综合", 
    "纬来戏剧", "纬来育乐", "年代新闻", "非凡新闻", "非凡商业", 
    "三立新闻", "三立台湾", "三立都会", "三立综合", "民视新闻", 
    "民视第一台", "民视台湾台", "民视", "台视新闻", "台视", 
    "中视新闻", "中视", "华视新闻", "华视", "公视", "翡翠台", 
    "明珠台", "ViuTV", "HOY TV", "HBO HITS", "HBO FAMILY", 
    "HBO SIGNATURE", "HBO", "AXN", "FOX", "DISCOVERY", 
    "国家地理", "动物星球"
]

# 繁体转简体映射
TRADITIONAL_TO_SIMPLIFIED = {
    '寰': '寰', '宇': '宇', '新': '新', '聞': '闻', '台': '台', 
    '臺': '台', '東': '东', '森': '森', '緯': '纬', '來': '来', 
    '鳳': '凤', '凰': '凰', '翡': '翡', '翠': '翠', '華': '华', 
    '視': '视', '民': '民', '公': '公', '中': '中', '劇': '剧', 
    '影': '影', '迷': '迷', '數': '数', '位': '位', '財': '财', 
    '經': '经', '體': '体', '育': '育', '亞': '亚', '綜': '综', 
    '藝': '艺', '樂': '乐', '戲': '戏', '曲': '曲', '電': '电', 
    '視': '视', '衛': '卫', '香': '香', '港': '港', '澳': '澳', 
    '門': '门', '湾': '湾', '灣': '湾', '洲': '洲', '国': '国', 
    '國': '国', '际': '际', '際': '际', '资': '资', '資': '资', 
    '讯': '讯', '訊': '讯', '天': '天', '动': '动', '動': '动', 
    '漫': '漫', '卡': '卡', '通': '通', '少': '少', '儿': '儿', 
    '兒': '儿', '惊': '惊', '驚': '惊', '悚': '悚', '悬': '悬', 
    '疑': '疑', '喜': '喜', '作': '作', '科': '科', '幻': '幻', 
    '紀': '纪', '實': '实', '靖': '靖', '洋': '洋'
}


def convert_t2s(text):
    """繁体转简体"""
    if not text:
        return ""
    return "".join(TRADITIONAL_TO_SIMPLIFIED.get(char, char) for char in text)


def print_separator(title):
    """打印分隔线"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_config():
    """打印当前港台配置"""
    print_separator("📋 当前港台组配置参数")
    print(f"  超时设置:")
    print(f"    - FFmpeg视频超时: {HKTW_CONFIG['timeout_video']}秒")
    print(f"    - 稳定性测试超时: {HKTW_CONFIG['timeout_stable']}秒")
    print(f"    - 基础连接超时: {HKTW_CONFIG['connect_timeout_basic']}秒")
    print(f"    - 基础读取超时: {HKTW_CONFIG['read_timeout_basic']}秒")
    print(f"    - 稳定性连接超时: {HKTW_CONFIG['connect_timeout_stable']}秒")
    
    print(f"\n  速度/抖动阈值:")
    print(f"    - 生死线速度: {HKTW_CONFIG['min_speed_dead']/1024:.2f} KB/s")
    print(f"    - 生死线抖动: {HKTW_CONFIG['max_jitter_dead']}秒")
    print(f"    - 正常速度: {HKTW_CONFIG['min_speed_normal']/1024:.2f} KB/s")
    print(f"    - 正常抖动: {HKTW_CONFIG['max_jitter_normal']}秒")
    print(f"    - 4K最低速度: {HKTW_CONFIG['min_speed_4k']/1024:.2f} KB/s")
    print(f"    - 4K最大抖动: {HKTW_CONFIG['max_jitter_4k']}秒")
    
    print(f"\n  质量门槛:")
    print(f"    - 最低分辨率: {HKTW_CONFIG['min_height']}p")
    print(f"    - 最低解码速率: {HKTW_CONFIG['min_speed_ratio']}x")
    print(f"    - 最大黑边: {HKTW_CONFIG['max_black_border']}像素")
    
    print(f"\n  宽松策略:")
    print(f"    - 允许低解码速率: {HKTW_CONFIG['allow_low_ratio']}")
    print(f"    - 严格僵尸检查: {HKTW_CONFIG['strict_zombie_check']}")
    print(f"    - 严格帧检查: {HKTW_CONFIG['strict_frame_check']}")


def step1_check_channel_name(url, raw_name=None):
    """
    第1步：频道名称检查和净化
    """
    print_separator("📝 第1步: 频道名称检查和净化")
    
    if not raw_name:
        # 从URL提取可能的名称
        parsed = urlparse(url)
        raw_name = parsed.path.split('/')[-1] or "未知频道"
    
    print(f"  原始名称: '{raw_name}'")
    
    # 检查名称长度
    name_lower = raw_name.lower().replace(" ", "")
    if len(name_lower) > 25:
        print(f"  ❌ 名称过长 ({len(name_lower)}字符 > 25), 原因: 可能是垃圾源")
        return None, "名称过长"
    
    # 检查无效关键词
    invalid_keywords = ["测试", "更新", "公告", "直播中", "暂留", "购", "经典香港电影", "财经", "香港综合"]
    matched_invalid = [k for k in invalid_keywords if k in name_lower]
    if matched_invalid:
        print(f"  ❌ 包含无效关键词: {matched_invalid}, 原因: 非正式直播频道")
        return None, f"无效关键词: {matched_invalid}"
    
    # 检查是否为港台频道
    is_hktw = any(k.lower() in name_lower for k in HK_TW_BRANDS) or \
              any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
    
    print(f"  港台频道识别: {'✅ 是' if is_hktw else '⚠️ 否 (但仍继续处理)'}")
    
    # 名称净化
    name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|（.*?）', '', raw_name)
    name = re.sub(r'[_#\-\s\t｜|]', '', name).upper()
    name = name.replace("雙語", "").replace("双语", "").replace("高清", "")\
               .replace("FHD", "").replace("HD", "").replace("4GTV", "")\
               .replace("备", "").replace("TVB功夫台", "TVB亚洲武俠")\
               .replace("AMC电影台", "AMC电影")
    name = convert_t2s(name)
    
    # 匹配知名港台频道
    sorted_channels = sorted(LOCAL_HKTW_CHANNELS, key=len, reverse=True)
    matched_channel = None
    for std_hk in sorted_channels:
        if std_hk in name:
            matched_channel = std_hk
            break
    
    if matched_channel:
        print(f"  ✅ 匹配知名频道: {matched_channel}")
        return matched_channel, "成功匹配"
    else:
        print(f"  ⚠️ 未匹配知名列表, 使用净化名称: '{name}'")
        return name, "使用净化名称"


def step2_dns_resolve(url):
    """
    第2步: DNS解析
    """
    print_separator("🌐 第2步: DNS解析")
    
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            print(f"  ❌ 无法从URL提取主机名")
            return None
        
        print(f"  主机名: {hostname}")
        
        start_time = time.time()
        ip = socket.gethostbyname(hostname)
        resolve_time = (time.time() - start_time) * 1000
        
        print(f"  ✅ 解析成功: {ip}")
        print(f"  ⏱️  解析耗时: {resolve_time:.0f}ms")
        return ip
        
    except socket.gaierror as e:
        print(f"  ❌ DNS解析失败: {e}")
        return None
    except Exception as e:
        print(f"  ❌ 解析异常: {e}")
        return None


def step3_basic_connectivity(url):
    """
    第3步: 基础连通性测试
    """
    print_separator("🔗 第3步: 基础连通性测试")
    
    connect_timeout = HKTW_CONFIG['connect_timeout_basic'] + 8  # 港台额外放宽8秒
    read_timeout = HKTW_CONFIG['read_timeout_basic'] + 6  # 港台额外放宽6秒
    
    print(f"  连接超时: {connect_timeout}秒")
    print(f"  读取超时: {read_timeout}秒")
    
    try:
        start_time = time.time()
        response = requests.get(
            url,
            headers=PLAYER_HEADERS,
            timeout=(connect_timeout, read_timeout),
            stream=True
        )
        connect_time = time.time() - start_time
        
        print(f"  ✅ HTTP状态码: {response.status_code}")
        print(f"  ⏱️  连接耗时: {connect_time:.2f}秒")
        
        # 打印响应头信息
        content_type = response.headers.get('Content-Type', 'unknown')
        content_length = response.headers.get('Content-Length', 'unknown')
        print(f"  📋 Content-Type: {content_type}")
        print(f"  📋 Content-Length: {content_length}")
        
        if response.status_code in [200, 206]:
            # 尝试读取首包
            try:
                chunk_start = time.time()
                chunk = next(response.iter_content(chunk_size=1024), None)
                chunk_time = time.time() - chunk_start
                
                if chunk:
                    print(f"  ✅ 首包接收成功")
                    print(f"  📦 首包大小: {len(chunk)} bytes")
                    print(f"  ⏱️  首包耗时: {chunk_time:.2f}秒")
                    return True
                else:
                    # 港台即使首包为空也放行
                    print(f"  ⚠️ 首包为空，但港台组宽松放行")
                    return True
            except Exception as e:
                # 港台即使首包读取异常也放行
                print(f"  ⚠️ 首包读取异常: {e}")
                print(f"  ✅ 港台组宽松放行")
                return True
        else:
            # 港台即使状态码不对也尝试放行
            print(f"  ⚠️ HTTP状态码异常，但港台组宽松放行")
            return True
            
    except requests.exceptions.ConnectTimeout:
        print(f"  ❌ 连接超时 (>{connect_timeout}秒)")
        return False
    except requests.exceptions.ReadTimeout:
        print(f"  ❌ 读取超时 (>{read_timeout}秒)")
        # 港台对超时也宽松放行
        print(f"  ✅ 港台组对超时宽松放行")
        return True
    except Exception as e:
        print(f"  ❌ 连接异常: {type(e).__name__} - {e}")
        # 检查是否是超时相关异常
        if "Timeout" in type(e).__name__ or "Connection" in type(e).__name__:
            print(f"  ✅ 港台组对超时/连接异常宽松放行")
            return True
        return False


def step4_stability_check(url):
    """
    第4步: 稳定性测速
    """
    print_separator("⚡ 第4步: 稳定性测速")
    
    is_4k = any(k in url.lower() for k in ["4k", "uhd", "239.252.220.212", "239.3.1.236"])
    
    connect_timeout = HKTW_CONFIG['connect_timeout_stable']
    read_timeout = HKTW_CONFIG['timeout_stable']
    
    print(f"  4K频道: {'是' if is_4k else '否'}")
    print(f"  测速时长: {read_timeout}秒")
    print(f"  连接超时: {connect_timeout}秒")
    
    try:
        start_time = time.time()
        response = requests.get(
            url,
            headers=PLAYER_HEADERS,
            timeout=(connect_timeout, read_timeout),
            stream=True
        )
        
        if response.status_code not in [200, 206]:
            print(f"  ❌ 测速响应失败 (HTTP {response.status_code})")
            return False, 0, 0
        
        total_bytes = 0
        last_chunk_time = time.time()
        max_jitter = 0
        chunk_count = 0
        
        print(f"\n  📊 开始接收数据...")
        
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                break
            
            current_time = time.time()
            jitter = current_time - last_chunk_time
            max_jitter = max(max_jitter, jitter)
            total_bytes += len(chunk)
            chunk_count += 1
            last_chunk_time = current_time
            
            elapsed = current_time - start_time
            
            # 每秒打印一次进度
            if chunk_count % 15 == 0 or elapsed >= read_timeout - 1:
                speed = total_bytes / elapsed if elapsed > 0 else 0
                print(f"    ⏱️  {elapsed:.1f}s | 已接收: {total_bytes/1024:.1f}KB | "
                      f"速度: {speed/1024:.1f}KB/s | 最大抖动: {max_jitter:.2f}s")
            
            if elapsed >= read_timeout:
                break
        
        duration = time.time() - start_time
        avg_speed = total_bytes / duration if duration > 0 else 0
        
        print(f"\n  📈 测速结果汇总:")
        print(f"    总时长: {duration:.2f}秒")
        print(f"    总数据: {total_bytes/1024:.1f}KB ({total_bytes} bytes)")
        print(f"    平均速度: {avg_speed/1024:.2f}KB/s")
        print(f"    最大抖动: {max_jitter:.2f}秒")
        print(f"    数据块数: {chunk_count}")
        
        # 判断通过与否
        print(f"\n  📋 判定标准:")
        print(f"    生死线速度: {HKTW_CONFIG['min_speed_dead']/1024:.2f}KB/s")
        print(f"    生死线抖动: {HKTW_CONFIG['max_jitter_dead']}秒")
        print(f"    正常速度: {HKTW_CONFIG['min_speed_normal']/1024:.2f}KB/s")
        print(f"    正常抖动: {HKTW_CONFIG['max_jitter_normal']}秒")
        
        # 生死线检查
        if max_jitter > HKTW_CONFIG['max_jitter_dead'] or avg_speed < HKTW_CONFIG['min_speed_dead']:
            print(f"\n  ❌ 生死线未达标!")
            if max_jitter > HKTW_CONFIG['max_jitter_dead']:
                print(f"     抖动 {max_jitter:.2f}s > {HKTW_CONFIG['max_jitter_dead']}s")
            if avg_speed < HKTW_CONFIG['min_speed_dead']:
                print(f"     速度 {avg_speed/1024:.2f}KB/s < {HKTW_CONFIG['min_speed_dead']/1024:.2f}KB/s")
            return False, avg_speed, max_jitter
        
        # 4K检查
        if is_4k:
            if max_jitter > HKTW_CONFIG['max_jitter_4k'] or avg_speed < HKTW_CONFIG['min_speed_4k']:
                print(f"\n  ❌ 4K规格未达标!")
                return False, avg_speed, max_jitter
            print(f"\n  ✅ 4K测速通过!")
            return True, avg_speed, max_jitter
        
        # 普通频道检查
        if max_jitter > HKTW_CONFIG['max_jitter_normal'] or avg_speed < HKTW_CONFIG['min_speed_normal']:
            print(f"\n  ❌ 稳定性未达标!")
            if max_jitter > HKTW_CONFIG['max_jitter_normal']:
                print(f"     抖动 {max_jitter:.2f}s > {HKTW_CONFIG['max_jitter_normal']}s")
            if avg_speed < HKTW_CONFIG['min_speed_normal']:
                print(f"     速度 {avg_speed/1024:.2f}KB/s < {HKTW_CONFIG['min_speed_normal']/1024:.2f}KB/s")
            return False, avg_speed, max_jitter
        
        print(f"\n  ✅ 测速通过!")
        return True, avg_speed, max_jitter
        
    except requests.exceptions.Timeout:
        print(f"  ❌ 测速超时")
        return False, 0, 0
    except Exception as e:
        print(f"  ❌ 测速异常: {type(e).__name__} - {e}")
        return False, 0, 0


def step5_ffmpeg_audit(url):
    """
    第5步: FFmpeg深度审计
    """
    print_separator("🎬 第5步: FFmpeg深度审计")
    
    # 查找ffmpeg
    ffmpeg_bin = '/root/ffmpeg' if __import__('os').path.exists('/root/ffmpeg') else 'ffmpeg'
    print(f"  FFmpeg路径: {ffmpeg_bin}")
    
    timeout = HKTW_CONFIG['timeout_video']
    timeout_us = str(int(timeout * 1000000))
    
    print(f"  超时设置: {timeout}秒")
    print(f"  最低分辨率: {HKTW_CONFIG['min_height']}p")
    print(f"  最低解码速率: {HKTW_CONFIG['min_speed_ratio']}x")
    
    cmd = [
        ffmpeg_bin, '-y', '-rw_timeout', timeout_us,
        '-i', url, '-vframes', '30',
        '-vf', 'cropdetect=limit=32:round=2',
        '-f', 'null', '-'
    ]
    
    print(f"\n  执行命令: {' '.join(cmd[:6])} ...")
    print(f"  (完整命令已隐藏URL)")
    
    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        duration = time.time() - start_time
        
        print(f"\n  ⏱️  FFmpeg执行耗时: {duration:.2f}秒")
        print(f"  📤 返回码: {result.returncode}")
        
        stderr = result.stderr
        
        # 提取视频流信息
        video_lines = [line for line in stderr.split('\n') if 'Stream #' in line and 'Video:' in line]
        
        if not video_lines:
            print(f"  ❌ 无法解析Video轨道元数据")
            # 打印部分stderr帮助诊断
            relevant_lines = [l for l in stderr.split('\n') if 'Error' in l or 'error' in l or 'Stream' in l]
            if relevant_lines:
                print(f"\n  📋 相关错误信息:")
                for line in relevant_lines[:10]:
                    print(f"    {line.strip()}")
            return False
        
        video_line = video_lines[0]
        print(f"\n  📹 视频流信息: {video_line.strip()}")
        
        # 解析分辨率
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', video_line)
        if res_match:
            width = int(res_match.group(1))
            height = int(res_match.group(2))
            print(f"  📐 分辨率: {width}x{height}")
            
            if height < HKTW_CONFIG['min_height']:
                print(f"  ❌ 分辨率过低 ({height}p < {HKTW_CONFIG['min_height']}p)")
                return False
            else:
                print(f"  ✅ 分辨率合格 ({height}p >= {HKTW_CONFIG['min_height']}p)")
        else:
            print(f"  ⚠️ 无法解析分辨率")
            width = height = 0
        
        # 解码速率检查
        speed_matches = re.findall(r'speed=\s*([\d\.]+)x', stderr)
        if speed_matches:
            final_speed = float(speed_matches[-1])
            print(f"  ⚡ 解码速率: {final_speed}x")
            
            if not HKTW_CONFIG.get('allow_low_ratio', False):
                if final_speed < HKTW_CONFIG['min_speed_ratio']:
                    print(f"  ❌ 解码速率过低 ({final_speed}x < {HKTW_CONFIG['min_speed_ratio']}x)")
                    return False
            print(f"  ✅ 解码速率检查通过 (宽松模式: {HKTW_CONFIG.get('allow_low_ratio', False)})")
        else:
            print(f"  ⚠️ 未检测到解码速率信息")
        
        # 帧检查
        if HKTW_CONFIG.get('strict_frame_check', True):
            if "frame=0" in stderr or "frame= " not in stderr:
                print(f"  ❌ 黑屏或无有效帧输出")
                return False
            print(f"  ✅ 帧检查通过")
        else:
            print(f"  ⚠️ 帧检查已跳过 (宽松模式)")
        
        # 僵尸错误检查
        if HKTW_CONFIG.get('strict_zombie_check', True):
            zombie_keywords = {
                "PPS id out of range": "NAL控制集错误",
                "Error parsing NAL unit": "NAL单元损坏",
                "Could not find ref with POC": "参考帧丢失",
                "corrupt decoded frame": "画面损坏"
            }
            found_zombie = False
            for kw, desc in zombie_keywords.items():
                if kw in stderr:
                    print(f"  ❌ 致命解码错误: {desc}")
                    found_zombie = True
            if not found_zombie:
                print(f"  ✅ 无致命解码错误")
            else:
                return False
        else:
            print(f"  ⚠️ 僵尸错误检查已跳过 (宽松模式)")
        
        # 黑边检查
        crop_matches = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr)
        if crop_matches and width > 0 and height > 0:
            last_crop = crop_matches[-1]
            crop_w, crop_h = int(last_crop[0]), int(last_crop[1])
            border_w = width - crop_w
            border_h = height - crop_h
            max_border = HKTW_CONFIG.get('max_black_border', 60)
            
            print(f"  🖼️  有效画面: {crop_w}x{crop_h}")
            print(f"  ⬛ 黑边: 水平{border_w}px, 垂直{border_h}px")
            
            if border_w > max_border or border_h > max_border:
                print(f"  ❌ 黑边过大 (>{max_border}像素)")
                return False
            else:
                print(f"  ✅ 黑边在合理范围内")
        else:
            print(f"  ℹ️  未检测到黑边信息或无法计算")
        
        print(f"\n  ✅ FFmpeg审计通过!")
        return True
        
    except subprocess.TimeoutExpired:
        print(f"  ❌ FFmpeg执行超时 (>{timeout}秒)")
        return False
    except FileNotFoundError:
        print(f"  ❌ 找不到FFmpeg: {ffmpeg_bin}")
        return False
    except Exception as e:
        print(f"  ❌ FFmpeg执行异常: {type(e).__name__} - {e}")
        return False


def diagnose_single_url(url, channel_name=None):
    """
    对单个直播链接进行完整诊断
    """
    print("\n" + "🔍" * 40)
    print("  港台直播源单链接深度诊断工具")
    print("🔍" * 40)
    
    print(f"\n📡 目标URL: {url}")
    if channel_name:
        print(f"📺 频道名称: {channel_name}")
    
    # 打印配置
    print_config()
    
    # 诊断结果汇总
    results = {
        "url": url,
        "steps": {},
        "passed": False,
        "final_name": None
    }
    
    # 第1步：频道名称检查
    name, reason = step1_check_channel_name(url, channel_name)
    results["steps"]["名称检查"] = {"passed": name is not None, "name": name, "reason": reason}
    if not name:
        print(f"\n❌ 诊断终止: {reason}")
        return results
    
    results["final_name"] = name
    
    # 第2步：DNS解析
    ip = step2_dns_resolve(url)
    results["steps"]["DNS解析"] = {"passed": ip is not None, "ip": ip}
    
    # 第3步：基础连通性
    connectivity = step3_basic_connectivity(url)
    results["steps"]["基础连通性"] = {"passed": connectivity}
    if not connectivity:
        print(f"\n❌ 诊断终止: 基础连通性失败")
        return results
    
    # 第4步：稳定性测速
    stable, speed, jitter = step4_stability_check(url)
    results["steps"]["稳定性测速"] = {
        "passed": stable,
        "speed_kbps": speed / 1024,
        "jitter": jitter
    }
    if not stable:
        print(f"\n❌ 诊断终止: 稳定性测速未通过")
        return results
    
    # 第5步：FFmpeg审计
    ffmpeg_pass = step5_ffmpeg_audit(url)
    results["steps"]["FFmpeg审计"] = {"passed": ffmpeg_pass}
    
    results["passed"] = ffmpeg_pass
    
    # 最终结果
    print_separator("📊 诊断结果汇总")
    print(f"\n  频道名称: {results['final_name']}")
    print(f"  URL: {url}")
    print(f"\n  各步骤结果:")
    for step_name, step_result in results["steps"].items():
        status = "✅ 通过" if step_result["passed"] else "❌ 失败"
        print(f"    {step_name}: {status}")
    
    print(f"\n  🏆 最终判定: {'✅ 通过' if results['passed'] else '❌ 未通过'}")
    
    if not results["passed"]:
        print(f"\n  💡 失败原因分析:")
        for step_name, step_result in results["steps"].items():
            if not step_result["passed"]:
                if step_name == "名称检查":
                    print(f"    - 名称检查: {step_result.get('reason', '未知')}")
                elif step_name == "DNS解析":
                    print(f"    - DNS解析失败，可能是域名不可达或DNS服务器问题")
                elif step_name == "基础连通性":
                    print(f"    - 基础连通性失败，服务器可能不可达或端口被封")
                elif step_name == "稳定性测速":
                    print(f"    - 速度: {step_result.get('speed_kbps', 0):.2f}KB/s")
                    print(f"    - 抖动: {step_result.get('jitter', 0):.2f}秒")
                    print(f"    - 可能原因: 跨境带宽不足或服务器限速")
                elif step_name == "FFmpeg审计":
                    print(f"    - 视频流质量问题，可能是编码损坏或分辨率过低")
    
    return results


def main():
    """主函数"""
    print("\n" + "🚀" * 40)
    print("  港台直播源质量审计 - 单链接调试工具")
    print("🚀" * 40)
    
    # 测试URL - 可以替换为任何港台直播源
    test_url = input("\n请输入要诊断的港台直播源URL: ").strip()
    
    if not test_url:
        # 默认测试URL
        test_url = "http://example.com/hktw_stream.m3u8"
        print(f"使用默认测试URL: {test_url}")
    
    channel_name = input("请输入频道名称 (可选): ").strip() or None
    
    # 执行诊断
    results = diagnose_single_url(test_url, channel_name)
    
    # 导出结果
    export = input("\n是否导出诊断报告为JSON? (y/n): ").strip().lower()
    if export == 'y':
        report_file = f"hktw_diagnose_{int(time.time())}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✅ 报告已保存至: {report_file}")
    
    print("\n" + "✅" * 40)
    print("  诊断完成!")
    print("✅" * 40)


if __name__ == "__main__":
    main()