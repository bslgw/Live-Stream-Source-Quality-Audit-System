#!/usr/bin/env python3
"""
港台直播源批量质量审计调试工具
读取 hk.m3u，对每条港台源执行完整诊断，输出详细结果到文件
"""

import requests
import re
import time
import subprocess
import socket
import json
import os
from urllib.parse import urlparse
from datetime import datetime

# ==================== 港台组配置 ====================
HKTW_CONFIG = {
    "timeout_video": 75,
    "timeout_stable": 25,
    "connect_timeout_basic": 40,
    "read_timeout_basic": 40,
    "min_speed_dead": 25,            # 0.68KB/s 生死线（极低）
    "max_jitter_dead": 3.0,           # 3秒最大抖动
    "min_speed_normal": 1432,         # 1.4KB/s 正常速度（极低）
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

PLAYER_HEADERS = {
    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
    'Accept': '*/*',
    'Connection': 'close'
}

HK_TW_BRANDS = [
    "凤凰", "鳳凰", "TVB", "翡翠台", "翡翠臺", "明珠台", "明珠臺", 
    "东森", "東森", "中天", "纬来", "緯來", "三立", "八大", "年代", 
    "非凡", "华视", "華視", "台视", "臺視", "民视", "民視", 
    "公视", "公視", "中视", "中視", "TVBS", "靖天", "靖洋", 
    "寰宇", "美亚", "美亞", "影迷数位", "影迷數位", "AMC", 
    "香港卫视", "香港衛視", "HBO", "AXN", "FOX", "DISCOVERY", 
    "国家地理", "动物星球", "VIUTV", "HOY TV"
]

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


def parse_hk_m3u(filepath):
    """解析 hk.m3u 文件，提取频道名和URL"""
    channels = []
    
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return channels
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for i in range(len(lines)):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            # 提取频道名
            name_match = re.search(r',(.+)$', line)
            if name_match:
                name = name_match.group(1).strip()
                # 取下一行的URL
                if i + 1 < len(lines):
                    url = lines[i + 1].strip()
                    if url.startswith('http'):
                        channels.append({
                            'raw_name': name,
                            'url': url
                        })
    
    return channels


def check_channel_name(raw_name, url):
    """Step 1: 频道名称检查和净化"""
    result = {
        'step': '名称检查',
        'passed': False,
        'raw_name': raw_name,
        'cleaned_name': None,
        'reason': '',
        'is_hktw': False,
        'matched_brand': None
    }
    
    name_lower = raw_name.lower().replace(" ", "")
    
    # 检查名称长度
    if len(name_lower) > 25:
        result['reason'] = f"名称过长 ({len(name_lower)}字符 > 25)"
        return result
    
    # 检查无效关键词
    invalid_keywords = ["测试", "更新", "公告", "直播中", "暂留", "购", "经典香港电影", "财经", "香港综合"]
    matched_invalid = [k for k in invalid_keywords if k in name_lower]
    if matched_invalid:
        result['reason'] = f"无效关键词: {matched_invalid}"
        return result
    
    # 检查是否为港台频道
    is_hktw = any(k.lower() in name_lower for k in HK_TW_BRANDS) or \
              any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
    result['is_hktw'] = is_hktw
    
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
    for std_hk in sorted_channels:
        if std_hk in name:
            result['matched_brand'] = std_hk
            result['cleaned_name'] = std_hk
            result['passed'] = True
            result['reason'] = f"匹配知名频道: {std_hk}"
            return result
    
    # 没有匹配但也不是无效的
    result['cleaned_name'] = name
    result['passed'] = True
    result['reason'] = f"使用净化名称: {name}"
    return result


def dns_resolve(url):
    """Step 2: DNS解析"""
    result = {
        'step': 'DNS解析',
        'passed': False,
        'hostname': '',
        'ip': '',
        'resolve_time_ms': 0,
        'error': ''
    }
    
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            result['error'] = "无法提取主机名"
            return result
        
        result['hostname'] = hostname
        
        start_time = time.time()
        ip = socket.gethostbyname(hostname)
        result['resolve_time_ms'] = (time.time() - start_time) * 1000
        result['ip'] = ip
        result['passed'] = True
        
    except socket.gaierror as e:
        result['error'] = f"DNS解析失败: {e}"
    except Exception as e:
        result['error'] = f"异常: {e}"
    
    return result


def basic_connectivity(url):
    """Step 3: 基础连通性测试"""
    result = {
        'step': '基础连通性',
        'passed': False,
        'http_status': 0,
        'connect_time': 0,
        'first_chunk': False,
        'first_chunk_size': 0,
        'content_type': '',
        'note': ''
    }
    
    connect_timeout = HKTW_CONFIG['connect_timeout_basic'] + 8
    read_timeout = HKTW_CONFIG['read_timeout_basic'] + 6
    
    try:
        start_time = time.time()
        response = requests.get(
            url,
            headers=PLAYER_HEADERS,
            timeout=(connect_timeout, read_timeout),
            stream=True
        )
        result['connect_time'] = time.time() - start_time
        result['http_status'] = response.status_code
        result['content_type'] = response.headers.get('Content-Type', '')
        
        if response.status_code in [200, 206]:
            try:
                chunk_start = time.time()
                chunk = next(response.iter_content(chunk_size=1024), None)
                
                if chunk:
                    result['first_chunk'] = True
                    result['first_chunk_size'] = len(chunk)
                    result['passed'] = True
                else:
                    result['note'] = "首包为空，但港台组宽松放行"
                    result['passed'] = True
            except:
                result['note'] = "首包读取异常，但港台组宽松放行"
                result['passed'] = True
        else:
            result['note'] = f"HTTP {response.status_code}，港台组宽松放行"
            result['passed'] = True
            
    except requests.exceptions.ConnectTimeout:
        result['error'] = f"连接超时 (>{connect_timeout}秒)"
        result['passed'] = False
    except requests.exceptions.ReadTimeout:
        result['error'] = f"读取超时 (>{read_timeout}秒)"
        result['note'] = "超时但港台组宽松放行"
        result['passed'] = True
    except Exception as e:
        err_name = type(e).__name__
        result['error'] = f"{err_name}: {e}"
        if "Timeout" in err_name or "Connection" in err_name:
            result['note'] = "超时/连接异常，港台组宽松放行"
            result['passed'] = True
    
    return result


def stability_check(url):
    """Step 4: 稳定性测速"""
    result = {
        'step': '稳定性测速',
        'passed': False,
        'duration': 0,
        'total_bytes': 0,
        'avg_speed_kbps': 0,
        'max_jitter': 0,
        'chunk_count': 0,
        'is_4k': False,
        'failure_reason': ''
    }
    
    result['is_4k'] = any(k in url.lower() for k in ["4k", "uhd", "239.252.220.212", "239.3.1.236"])
    
    connect_timeout = HKTW_CONFIG['connect_timeout_stable']
    read_timeout = HKTW_CONFIG['timeout_stable']
    
    try:
        start_time = time.time()
        response = requests.get(
            url,
            headers=PLAYER_HEADERS,
            timeout=(connect_timeout, read_timeout),
            stream=True
        )
        
        if response.status_code not in [200, 206]:
            result['failure_reason'] = f"HTTP {response.status_code}"
            return result
        
        total_bytes = 0
        last_chunk_time = time.time()
        max_jitter = 0
        chunk_count = 0
        
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                break
            
            current_time = time.time()
            jitter = current_time - last_chunk_time
            max_jitter = max(max_jitter, jitter)
            total_bytes += len(chunk)
            chunk_count += 1
            last_chunk_time = current_time
            
            if (current_time - start_time) >= read_timeout:
                break
        
        duration = time.time() - start_time
        result['duration'] = duration
        result['total_bytes'] = total_bytes
        result['max_jitter'] = max_jitter
        result['chunk_count'] = chunk_count
        
        if duration > 0:
            result['avg_speed_kbps'] = (total_bytes / duration) / 1024
        
        # 生死线检查
        if max_jitter > HKTW_CONFIG['max_jitter_dead']:
            result['failure_reason'] = f"抖动 {max_jitter:.2f}s > 生死线 {HKTW_CONFIG['max_jitter_dead']}s"
            return result
        
        if total_bytes / max(duration, 0.1) < HKTW_CONFIG['min_speed_dead']:
            result['failure_reason'] = f"速度 {result['avg_speed_kbps']:.2f}KB/s < 生死线 {HKTW_CONFIG['min_speed_dead']/1024:.2f}KB/s"
            return result
        
        # 4K检查
        if result['is_4k']:
            if max_jitter > HKTW_CONFIG['max_jitter_4k'] or \
               (total_bytes / max(duration, 0.1)) < HKTW_CONFIG['min_speed_4k']:
                result['failure_reason'] = "4K规格未达标"
                return result
            result['passed'] = True
            return result
        
        # 普通频道检查
        if max_jitter > HKTW_CONFIG['max_jitter_normal']:
            result['failure_reason'] = f"抖动 {max_jitter:.2f}s > 正常 {HKTW_CONFIG['max_jitter_normal']}s"
            return result
        
        if total_bytes / max(duration, 0.1) < HKTW_CONFIG['min_speed_normal']:
            result['failure_reason'] = f"速度 {result['avg_speed_kbps']:.2f}KB/s < 正常 {HKTW_CONFIG['min_speed_normal']/1024:.2f}KB/s"
            return result
        
        result['passed'] = True
        
    except Exception as e:
        result['failure_reason'] = f"{type(e).__name__}: {e}"
    
    return result


def ffmpeg_audit(url, category=""):
    """Step 5: FFmpeg深度审计"""
    result = {
        'step': 'FFmpeg审计',
        'passed': False,
        'duration': 0,
        'return_code': 0,
        'width': 0,
        'height': 0,
        'decode_speed': 0,
        'has_frames': False,
        'crop_w': 0,
        'crop_h': 0,
        'border_w': 0,
        'border_h': 0,
        'zombie_errors': [],
        'failure_reason': ''
    }
    
    ffmpeg_bin = '/root/ffmpeg' if os.path.exists('/root/ffmpeg') else 'ffmpeg'
    timeout = HKTW_CONFIG['timeout_video']
    timeout_us = str(int(timeout * 1000000))
    
    cmd = [
        ffmpeg_bin, '-y', '-rw_timeout', timeout_us,
        '-i', url, '-vframes', '30',
        '-vf', 'cropdetect=limit=32:round=2',
        '-f', 'null', '-'
    ]
    
    try:
        start_time = time.time()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        result['duration'] = time.time() - start_time
        result['return_code'] = proc.returncode
        
        if proc.returncode != 0:
            result['failure_reason'] = f"返回码 {proc.returncode}"
            return result
        
        stderr = proc.stderr
        
        # 解析视频流
        video_lines = [l for l in stderr.split('\n') if 'Stream #' in l and 'Video:' in l]
        if not video_lines:
            result['failure_reason'] = "无法解析Video轨道元数据"
            return result
        
        # 分辨率
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', video_lines[0])
        if res_match:
            result['width'] = int(res_match.group(1))
            result['height'] = int(res_match.group(2))
        
        # 🔴 核心：4K分辨率检查
        if category == "4K超清":
            if result['height'] < 2160:
                result['failure_reason'] = f"归类为4K但分辨率仅{result['height']}p（要求≥2160p）"
                return result
        else:
            if result['height'] < HKTW_CONFIG['min_height']:
                result['failure_reason'] = f"分辨率 {result['height']}p < {HKTW_CONFIG['min_height']}p"
                return result
        
        # 解码速率
        speed_matches = re.findall(r'speed=\s*([\d\.]+)x', stderr)
        if speed_matches:
            result['decode_speed'] = float(speed_matches[-1])
            if not HKTW_CONFIG.get('allow_low_ratio', False):
                if result['decode_speed'] < HKTW_CONFIG['min_speed_ratio']:
                    result['failure_reason'] = f"解码速率 {result['decode_speed']}x < {HKTW_CONFIG['min_speed_ratio']}x"
                    return result
        
        # 帧检查
        if HKTW_CONFIG.get('strict_frame_check', True):
            if "frame=0" in stderr or "frame= " not in stderr:
                result['failure_reason'] = "黑屏或无有效帧"
                return result
            result['has_frames'] = True
        
        # 僵尸错误
        if HKTW_CONFIG.get('strict_zombie_check', True):
            zombie_keywords = {
                "PPS id out of range": "NAL控制集错误",
                "Error parsing NAL unit": "NAL单元损坏",
                "Could not find ref with POC": "参考帧丢失",
                "corrupt decoded frame": "画面损坏"
            }
            for kw, desc in zombie_keywords.items():
                if kw in stderr:
                    result['zombie_errors'].append(desc)
            if result['zombie_errors']:
                result['failure_reason'] = f"致命解码错误: {result['zombie_errors']}"
                return result
        
        # 黑边检查
        crop_matches = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr)
        if crop_matches and result['width'] > 0:
            last_crop = crop_matches[-1]
            result['crop_w'] = int(last_crop[0])
            result['crop_h'] = int(last_crop[1])
            result['border_w'] = result['width'] - result['crop_w']
            result['border_h'] = result['height'] - result['crop_h']
            
            max_border = HKTW_CONFIG.get('max_black_border', 60)
            if result['border_w'] > max_border or result['border_h'] > max_border:
                result['failure_reason'] = f"黑边过大 (水平{result['border_w']}px, 垂直{result['border_h']}px > {max_border}px)"
                return result
        
        result['passed'] = True
        
    except subprocess.TimeoutExpired:
        result['failure_reason'] = f"FFmpeg超时 (>{timeout}秒)"
    except FileNotFoundError:
        result['failure_reason'] = f"找不到FFmpeg: {ffmpeg_bin}"
    except Exception as e:
        result['failure_reason'] = f"{type(e).__name__}: {e}"
    
    return result


def diagnose_channel(channel):
    """对单个频道执行完整诊断"""
    url = channel['url']
    raw_name = channel['raw_name']
    
    result = {
        'raw_name': raw_name,
        'url': url,
        'steps': [],
        'final_passed': False,
        'final_name': '',
        'final_category': ''
    }
    
    # Step 1: 名称检查
    step1 = check_channel_name(raw_name, url)
    result['steps'].append(step1)
    
    if not step1['passed']:
        result['final_passed'] = False
        return result
    
    result['final_name'] = step1['cleaned_name']
    result['final_category'] = "4K超清" if "4K" in raw_name.upper() else "港台频道"
    
    # Step 2: DNS解析
    step2 = dns_resolve(url)
    result['steps'].append(step2)
    
    # Step 3: 基础连通性
    step3 = basic_connectivity(url)
    result['steps'].append(step3)
    
    if not step3['passed']:
        result['final_passed'] = False
        return result
    
    # Step 4: 稳定性测速
    step4 = stability_check(url)
    result['steps'].append(step4)
    
    if not step4['passed']:
        result['final_passed'] = False
        return result
    
    # Step 5: FFmpeg审计（传入category用于4K检查）
    step5 = ffmpeg_audit(url, result['final_category'])
    result['steps'].append(step5)
    
    result['final_passed'] = step5['passed']
    
    return result


def write_report(all_results, config):
    """写入详细报告"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 1. 详细JSON报告
    json_file = f"hktw_batch_report_{timestamp}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'config': {k: v for k, v in config.items() if not k.startswith('_')},
            'total': len(all_results),
            'passed': sum(1 for r in all_results if r['final_passed']),
            'failed': sum(1 for r in all_results if not r['final_passed']),
            'results': all_results
        }, f, indent=2, ensure_ascii=False, default=str)
    
    # 2. 可读文本报告
    txt_file = f"hktw_batch_report_{timestamp}.txt"
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("  港台直播源批量质量审计报告\n")
        f.write(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        # 配置摘要
        f.write("📋 当前配置参数:\n")
        f.write(f"  速度阈值: 生死线={config['min_speed_dead']/1024:.2f}KB/s, 正常={config['min_speed_normal']/1024:.2f}KB/s\n")
        f.write(f"  抖动阈值: 生死线={config['max_jitter_dead']}s, 正常={config['max_jitter_normal']}s\n")
        f.write(f"  最低分辨率: {config['min_height']}p\n")
        f.write(f"  超时设置: 视频={config['timeout_video']}s, 测速={config['timeout_stable']}s, 连接={config['connect_timeout_basic']}s\n")
        f.write(f"  宽松策略: 允许低解码率={config['allow_low_ratio']}, 严格帧检查={config['strict_frame_check']}, 严格僵尸检查={config['strict_zombie_check']}\n")
        f.write("\n" + "=" * 80 + "\n\n")
        
        # 总体统计
        passed = [r for r in all_results if r['final_passed']]
        failed = [r for r in all_results if not r['final_passed']]
        
        f.write(f"📊 总体统计:\n")
        f.write(f"  总频道数: {len(all_results)}\n")
        f.write(f"  ✅ 通过: {len(passed)}\n")
        f.write(f"  ❌ 未通过: {len(failed)}\n\n")
        
        # 失败原因统计
        f.write("🔍 失败原因分布:\n")
        fail_reasons = {}
        fail_steps = {}
        for r in failed:
            for step in r['steps']:
                if not step['passed']:
                    reason = step.get('failure_reason', step.get('reason', step.get('error', '未知')))
                    fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                    fail_steps[step['step']] = fail_steps.get(step['step'], 0) + 1
                    break
        
        f.write("\n  按步骤分布:\n")
        for step, count in sorted(fail_steps.items(), key=lambda x: -x[1]):
            f.write(f"    {step}: {count}条\n")
        
        f.write("\n  按具体原因分布:\n")
        for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1])[:20]:
            f.write(f"    [{count}条] {reason}\n")
        
        f.write("\n" + "=" * 80 + "\n\n")
        
        # 详细结果
        f.write("📝 详细结果:\n\n")
        
        for i, r in enumerate(all_results, 1):
            status = "✅ 通过" if r['final_passed'] else "❌ 未通过"
            f.write(f"[{i}/{len(all_results)}] {status}\n")
            f.write(f"  原始名称: {r['raw_name']}\n")
            f.write(f"  最终名称: {r['final_name']}\n")
            f.write(f"  分类: {r['final_category']}\n")
            f.write(f"  URL: {r['url']}\n")
            
            for step in r['steps']:
                step_status = "✅" if step['passed'] else "❌"
                f.write(f"  {step_status} {step['step']}: ")
                
                if step['step'] == '名称检查':
                    f.write(f"{step.get('reason', '')} → {step.get('cleaned_name', '')}")
                elif step['step'] == 'DNS解析':
                    f.write(f"{step.get('hostname', '')} → {step.get('ip', '')} ({step.get('resolve_time_ms', 0):.0f}ms)")
                elif step['step'] == '基础连通性':
                    f.write(f"HTTP {step.get('http_status', 0)} | {step.get('note', step.get('error', ''))}")
                elif step['step'] == '稳定性测速':
                    if step.get('avg_speed_kbps', 0) > 0:
                        f.write(f"速度={step.get('avg_speed_kbps', 0):.2f}KB/s | 抖动={step.get('max_jitter', 0):.2f}s")
                    else:
                        f.write(f"{step.get('failure_reason', '')}")
                elif step['step'] == 'FFmpeg审计':
                    if step.get('height', 0) > 0:
                        f.write(f"分辨率={step.get('width', 0)}x{step.get('height', 0)} | 解码速率={step.get('decode_speed', 0)}x")
                    if not step['passed']:
                        f.write(f" | 失败原因: {step.get('failure_reason', '')}")
                
                f.write("\n")
            
            f.write("\n")
    
    # 3. 通过列表（可直接用作 gt.m3u）
    passed_file = f"hktw_passed_{timestamp}.m3u"
    with open(passed_file, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")
        f.write(f"# 港台频道质量审计通过列表 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        for r in passed:
            f.write(f'#EXTINF:-1 group-title="{r["final_category"]}",{r["final_name"]}\n')
            f.write(f'{r["url"]}\n')
    
    # 4. 失败列表（便于分析）
    failed_file = f"hktw_failed_{timestamp}.txt"
    with open(failed_file, 'w', encoding='utf-8') as f:
        f.write(f"港台频道失败列表 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        for r in failed:
            fail_step = ""
            fail_reason = ""
            for step in r['steps']:
                if not step['passed']:
                    fail_step = step['step']
                    fail_reason = step.get('failure_reason', step.get('reason', step.get('error', '未知')))
                    break
            f.write(f"名称: {r['raw_name']} → {r['final_name']}\n")
            f.write(f"URL: {r['url']}\n")
            f.write(f"失败步骤: {fail_step}\n")
            f.write(f"失败原因: {fail_reason}\n")
            f.write("-" * 40 + "\n")
    
    return json_file, txt_file, passed_file, failed_file


def main():
    """主函数"""
    print("\n" + "🚀" * 40)
    print("  港台直播源批量质量审计调试工具")
    print("🚀" * 40)
    
    # 读取 hk.m3u
    input_file = "hk.m3u"
    if not os.path.exists(input_file):
        print(f"\n❌ 找不到 {input_file} 文件！")
        print("请将港台频道数据保存为 hk.m3u 放在当前目录下。")
        return
    
    channels = parse_hk_m3u(input_file)
    print(f"\n📂 已加载 {len(channels)} 条港台频道")
    
    if not channels:
        print("❌ 未解析到任何频道，请检查 hk.m3u 格式。")
        return
    
    # 打印配置
    print("\n📋 当前配置:")
    print(f"  速度: 生死线={HKTW_CONFIG['min_speed_dead']/1024:.2f}KB/s, 正常={HKTW_CONFIG['min_speed_normal']/1024:.2f}KB/s")
    print(f"  抖动: 生死线={HKTW_CONFIG['max_jitter_dead']}s, 正常={HKTW_CONFIG['max_jitter_normal']}s")
    print(f"  最低分辨率: {HKTW_CONFIG['min_height']}p")
    print(f"  超时: 视频={HKTW_CONFIG['timeout_video']}s, 测速={HKTW_CONFIG['timeout_stable']}s")
    
    # 确认开始
    print(f"\n⚠️  将对 {len(channels)} 条频道进行完整检测，预计耗时较长。")
    confirm = input("确认开始? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消。")
        return
    
    # 执行批量检测
    all_results = []
    start_time = time.time()
    
    for i, ch in enumerate(channels, 1):
        print(f"\n[{i}/{len(channels)}] 检测: {ch['raw_name'][:40]}...")
        
        try:
            result = diagnose_channel(ch)
            all_results.append(result)
            
            status = "✅" if result['final_passed'] else "❌"
            print(f"  {status} {'通过' if result['final_passed'] else '未通过'}")
            
            # 显示失败原因
            if not result['final_passed']:
                for step in result['steps']:
                    if not step['passed']:
                        reason = step.get('failure_reason', step.get('reason', step.get('error', '')))
                        print(f"     失败于 {step['step']}: {reason[:80]}")
                        break
        
        except Exception as e:
            print(f"  ❌ 检测异常: {e}")
            all_results.append({
                'raw_name': ch['raw_name'],
                'url': ch['url'],
                'steps': [],
                'final_passed': False,
                'final_name': ch['raw_name'],
                'final_category': '港台频道',
                'error': str(e)
            })
    
    total_time = time.time() - start_time
    
    # 统计
    passed = [r for r in all_results if r['final_passed']]
    failed = [r for r in all_results if not r['final_passed']]
    
    print(f"\n📊 检测完成!")
    print(f"  总耗时: {total_time/60:.1f}分钟")
    print(f"  总频道: {len(all_results)}")
    print(f"  ✅ 通过: {len(passed)}")
    print(f"  ❌ 未通过: {len(failed)}")
    
    # 写入报告
    print(f"\n📝 正在生成报告...")
    json_file, txt_file, passed_file, failed_file = write_report(all_results, HKTW_CONFIG)
    
    print(f"\n📁 报告文件:")
    print(f"  详细JSON: {json_file}")
    print(f"  可读文本: {txt_file}")
    print(f"  通过列表: {passed_file}")
    print(f"  失败列表: {failed_file}")
    
    # 失败原因Top5
    fail_reasons = {}
    for r in failed:
        for step in r['steps']:
            if not step['passed']:
                reason = step.get('failure_reason', step.get('reason', step.get('error', '未知')))
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                break
    
    print(f"\n🔍 失败原因 Top 5:")
    for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1])[:5]:
        print(f"  [{count}条] {reason[:100]}")
    
    print(f"\n✅ 批量调试完成！请查看报告文件分析数据。")


if __name__ == "__main__":
    main()