import requests
import base64
import json
import re
import time
import sys
import subprocess
import socket
import os
import threading
from urllib.parse import urlparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

print("=== 直播源质量审计系统 (港台直通无阻多源兼容版) ===")

CONFIG_FILE_PATH = "./config.json"

# ==================== ⚙️ 出厂默认配置数据区 (用户无 config.json 时兜底) ====================
DEFAULT_MAINLAND_CONFIG = {
    'timeout_video': 20.0,          # FFmpeg 整体检测硬超时 (秒)
    'timeout_stable': 5.0,          # Step 6 测速拉流维持时间 (秒)
    'connect_timeout_basic': 6,     # Step 2 基础连通性握手超时 (秒)
    'read_timeout_basic': 4,        # Step 2 基础连通性首包响应超时 (秒)
    'min_speed_dead': 100 * 1024,   # 绝对流速生死线 (Bytes/s) -> 100KB/s
    'max_jitter_dead': 3.0,         # 绝对抖动生死线 (秒)
    'min_speed_normal': 180 * 1024, # 高清流速低保线 (Bytes/s) -> 180KB/s
    'max_jitter_normal': 2.0,       # 稳定性抖动限制 (秒)
    'min_height': 720,              # 物理分辨率拦截底线 (720p)
    'min_speed_ratio': 0.8          # FFmpeg 解码传输速率底线
}

DEFAULT_HKTW_CONFIG = {
    'timeout_video': 30.0,          # 针对跨境传输慢，延长至 30 秒
    'timeout_stable': 8.0,          # 测速拉流时间拉长，平抑波动
    'connect_timeout_basic': 10,    # 跨境物理握手放宽至 10 秒
    'read_timeout_basic': 6,        # 跨境首包流传输放宽至 6 秒
    'min_speed_dead': 60 * 1024,    # 生死线降至 60KB/s
    'max_jitter_dead': 5.0,         # 允许最大 5.0 秒抖动
    'min_speed_normal': 100 * 1024, # 常规流速降至 100KB/s
    'max_jitter_normal': 4.0,       # 常规网络抖动放宽至 4.0 秒
    'min_height': 480,              # 画质拦截底线降至 480p
    'min_speed_ratio': 0.5          # 允许因跨境掉帧导致速率阶段性倒挂降至 0.5x
}

DEFAULT_HK_TW_BRANDS = [
    "凤凰", "鳳凰", "TVB", "翡翠台", "翡翠臺", "明珠台", "明珠臺", "东森", "東森", "中天", "纬来", "緯來", 
    "三立", "八大", "年代", "非凡", "华视", "華視", "台视", "臺視", "民视", "民視", "公视", "公視", 
    "中视", "中視", "TVBS", "靖天", "靖洋", "寰宇", "美亚", "美亞", "影迷数位", "影迷數位", "AMC", "香港卫视", "香港衛視",
    "HBO", "AXN", "FOX", "DISCOVERY", "国家地理", "动物星球", "VIUTV", "HOY TV"
]

# 📡 多源配置列表：支持原版加密源，也完美支持 GitHub 的明文 m3u/m3u8 订阅链接
DEFAULT_CONFIG_SOURCES = [
    "https://ppsll.cc.cd/ppsll",   
]

# ==================== 🔌 配置热加载引擎 ====================
def load_or_create_user_config():
    """自动化配置管理：支持多源配置列表写入本地 config.json"""
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"💡 未检测到本地配置，正在为您自动生成个性化模板: {CONFIG_FILE_PATH}")
        factory_data = {
            "MAINLAND_CONFIG": DEFAULT_MAINLAND_CONFIG,
            "HKTW_CONFIG": DEFAULT_HKTW_CONFIG,
            "HK_TW_BRANDS": DEFAULT_HK_TW_BRANDS,
            "CONFIG_SOURCES": DEFAULT_CONFIG_SOURCES
        }
        try:
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(factory_data, f, indent=2, ensure_ascii=False)
            print("   -> 默认出厂配置模版生成成功！用户未来可自由修改此文件进行个性化清洗。")
        except Exception as e:
            print(f"⚠️ 写入配置文件失败: {e}，将采用内存默认参数运行。")
        return DEFAULT_MAINLAND_CONFIG, DEFAULT_HKTW_CONFIG, DEFAULT_HK_TW_BRANDS, DEFAULT_CONFIG_SOURCES
    else:
        print(f"🚀 检测到个性化配置文件，正在注入用户自定义过滤参数...")
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                user_data = json.load(f)
            m_cfg = user_data.get("MAINLAND_CONFIG", DEFAULT_MAINLAND_CONFIG)
            h_cfg = user_data.get("HKTW_CONFIG", DEFAULT_HKTW_CONFIG)
            brands = user_data.get("HK_TW_BRANDS", DEFAULT_HK_TW_BRANDS)
            sources = user_data.get("CONFIG_SOURCES", DEFAULT_CONFIG_SOURCES)
            print("   -> 成功加载个性化矩阵！系统已按您的专属阈值重新对齐。")
            return m_cfg, h_cfg, brands, sources
        except Exception as e:
            print(f"❌ 解析 config.json 失败: {e}。为保障系统不崩溃，自动回滚至出厂安全参数。")
            return DEFAULT_MAINLAND_CONFIG, DEFAULT_HKTW_CONFIG, DEFAULT_HK_TW_BRANDS, DEFAULT_CONFIG_SOURCES

# 实时加载配置
MAINLAND_CONFIG, HKTW_CONFIG, HK_TW_BRANDS, CONFIG_SOURCES = load_or_create_user_config()

# ==================== 🛠️ 其余静态核心字典区 ====================
MAX_WORKERS = 5  

PROVINCIAL_SATELLITE_CHANNELS = [
    "安徽卫视", "北京卫视", "兵团卫视", "重庆卫视", "东方卫视", "东南卫视", 
    "广东卫视", "广西卫视", "甘肃卫视", "贵州卫视", "湖南卫视", "湖北卫视", 
    "河南卫视", "河北卫视", "黑龙江卫视", "海南卫视", "江苏卫视", "江西卫视", 
    "吉林卫视", "辽宁卫视", "宁夏卫视", "青海卫视", "山东卫视", "深圳卫视", 
    "四川卫视", "陕西卫视", "山西卫视", "三沙卫视", "天津卫视", "厦门卫视", 
    "新疆卫视", "西藏卫视", "云南卫视", "浙江卫视", "金鹰卡通", "卡酷少儿", "嘉佳卡通"
]

STANDARD_CCTV = {
    "1": "综合", "2": "财经", "3": "综艺", "4": "中文国际", "5": "体育", 
    "6": "电影", "7": "国防军事", "8": "电视剧", "9": "纪录", "10": "科教", 
    "11": "戏曲", "12": "社会与法", "13": "新闻", "14": "少儿", "15": "音乐", 
    "16": "奥林匹克", "17": "农业农村"
}

TRADITIONAL_TO_SIMPLIFIED = {
    '寰': '寰', '宇': '宇', '新': '新', '聞': '闻', '台': '台', '臺': '台', '檯': '台',
    '東': '东', '森': '森', '緯': '纬', '來': '来', '鳳': '凤', '凰': '凰', '翡': '翡',
    '翠': '翠', '華': '华', '視': '视', '民': '民', '公': '公', '中': '中', '劇': '剧',
    '影': '影', '迷': '迷', '數': '数', '位': '位', '財': '财', '經': '经', '體': '体',
    '育': '育', '亞': '亚', '綜': '综', '藝': '艺', '樂': '乐', '戲': '戏', '曲': '曲',
    '電': '电', '視': '视', '台': '台', '衛': '卫', '香': '香', '港': '港', '澳': '澳',
    '門': '门', '湾': '湾', '灣': '湾', '亞': '亚', '洲': '洲', '国': '国', '國': '国', 
    '际': '际', '際': '际', '资': '资', '資': '资', '讯': '讯', '訊': '讯', '天': '天', 
    '动': '动', '動': '动', '漫': '漫', '卡': '卡', '通': '通', '少': '少', '儿': '儿', 
    '兒': '儿', '惊': '惊', '驚': '惊', '悚': '悚', '悬': '悬', '疑': '疑', '喜': '喜', 
    '剧': '剧', '作': '作', '科': '科', '幻': '幻', '紀': '纪', '實': '实'
}

PLAYER_HEADERS = {
    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
    'Accept': '*/*',
    'Connection': 'close'
}

CORRECTION_DB = [
    {"match": "http://rihou.cc:555/tv/", "action": "discard"},  
    {"match": "http://jiange.dns.navy:10001", "action": "discard"},                               
    {"match": "http://lbyjlt.vv5678.cn:8880", "action": "discard"},            
    {"match": "http://xhzza.v6.navy:34040","action": "discard"},     
    {"match": "http://120.87.19.109:80/PLTV/", "action": "discard"},     
    {"match": "http://rrs01.hw.gmcc.net:8088", "action": "discard"},     
    {"match": "http://27.154.99.234:3386/", "action": "discard"},     
    {"match": "http://106.87.50.30:8888", "action": "discard"},     
    {"match": "http://106.116.242.203:9999/rtp", "action": "discard"},     
    {"match": "http://118.251.16.185:8188/udp", "action": "discard"},     
    {"match": "http://111.162.205.209:8686/rtp", "action": "discard"},                                  
    {"match": "https://live.ottiptv.cc", "action": "discard"},            
    {"match": "https://live.ottiptv.cc/huya", "action": "discard"},     
    {"match": "http://php.jdshipin.com:8880", "action": "discard"},     
    {"match": "https://t26.cdn2020.com/video/m3u8", "action": "discard"},  
    {"match": "https://iptv.catvod.com", "action": "discard"},     
    {"match": "http://38.75.136.137:98/gslb/dsdqca", "action": "discard"},     
    {"match": "http://182.61.15.163:9080", "action": "discard"},     
    {"match": "https://liveh12.vtvprime.vn/", "action": "discard"}, 
    {"match": "http://go.bkpcp.top/mg", "action": "discard"},
    {"match": "http://tvpull.dxhmt.cn:9081/tv", "action": "discard"},
    {"match": "http://m.061899.xyz/mg/", "action": "discard"},
    {"match": "https://liveh12.vtvprime.vn/", "action": "discard"},
    {"match": "http://j.s.bkpcp.top//", "action": "discard"},
    {"match": "https://live01-cn-ali.zytlka.com/", "action": "discard"},        
    {"match": "http://s.rocketdns.info:8080", "action": "discard"},   
    {"match": "http://bot22.top:19999/udp/", "action": "discard"},   
    {"match": "http://k.061899.xyz", "action": "discard"},   
    {"match": "https://www.goodiptv.club/douyu", "action": "discard"},   
    {"match": "http://81.137.213.119:4203/bysid", "action": "discard"},   
    {"match": "https://live.ottiptv.cc/yy", "action": "discard"},   
    {"match": "https://t33.cdn2020.com/video/m3u8", "action": "discard"},   
    {"match": "/cdnlive/", "action": "discard"},                   
    {"match": "http://220.167.170.144:4000/rtp/239.120.1.111:8254", "action": "discard"}, 
    {"match": "http://183.164.237.29:8888/rtp/238.1.78.137:6968", "action": "discard"}, 
    {"match": "http://129.211.14.102", "action": "discard"},    
    {"match": "https://chibrics.mediacdn.ru/cdn/brics/chinese/playlist.m3u8", "action": "discard"}, 
   #{"match": "http://129.211.14.102", "action": "rename","value":""},    
]

def execute_link_correction_and_blacklist(raw_channels):
    cleaned_channels = []
    discard_count = 0
    rename_count = 0
    for item in raw_channels:
        url = item.get("url", "")
        raw_name = item.get("raw_name", "")
        if not url: continue
        is_discarded = False
        current_name = raw_name
        
        for rule in CORRECTION_DB:
            match_target = rule["match"]
            action = rule["action"]
            if action == "discard" and (match_target in url):
                name_lower = raw_name.lower().replace(" ", "")
                is_hk = any(k.lower() in name_lower for k in HK_TW_BRANDS) or any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
                if not is_hk:
                    register_discard(1, f"纠正库黑名单特征或已知失效IP通配拦截 (命中特征: {match_target})", url, is_hktw=False)
                is_discarded = True
                discard_count += 1
                break  
            elif action == "rename" and (match_target == url):
                current_name = rule["value"]
                rename_count += 1

        if not is_discarded:
            item["raw_name"] = current_name
            cleaned_channels.append(item)
            
    print(f"   [🧠 纠正库拦截报告] 预筛选处理完毕。批量拉黑干掉 {discard_count} 条，精准改名纠偏 {rename_count} 条。")
    return cleaned_channels

# ==================== 🔎 丢弃审计追踪与发现模块 ====================
discard_lock = threading.Lock()
discard_registry_domestic = defaultdict(list) 

def register_discard(step_num, reason, url, is_hktw=False):
    if is_hktw:
        return
    header = f"====丢弃步骤{step_num}  {reason}  ======="
    with discard_lock:
        if url not in discard_registry_domestic[header]:
            discard_registry_domestic[header].append(url)

# ==================== 🛠️ 基础文本净化组件 ====================
def heal_mojibake(text):
    if not text: return ""
    mojibake_features = ['闋', '槌', '嚢', '涓', '鏂', '闆', '褰', '璺', '缈', '繝', '鐛', '嗃', '鑿']
    if any(f in text for f in mojibake_features):
        try:
            recovered = text.encode('gbk', errors='ignore').decode('utf-8', errors='ignore')
            if recovered and not any(f in recovered for f in mojibake_features):
                return recovered
        except: pass
    return text

def convert_t2s(text):
    if not text: return ""
    return "".join(TRADITIONAL_TO_SIMPLIFIED.get(char, char) for char in text)

# ==================== 🛠️ 核心步骤业务处理区 ====================
def step1_fetch_all_configs(urls_list):
    """【修复并升级】自适应抓取多源主配置：智能识别并兼容解密 JSON 配置与明文 M3U/M3U8 订阅源"""
    print("[Step 1] 正在智能抓取并解析多源主配置...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    combined_lives = []
    seen_source_urls = set()
    
    for idx, main_url in enumerate(urls_list, 1):
        print(f"   -> 正在加载 ({idx}/{len(urls_list)}): {main_url}")
        
        # 兼容策略 1：通过 URL 后缀识别直连明文订阅源（避免不必要的下载和强行 Base64 解码报错）
        lower_url = main_url.lower()
        if any(ext in lower_url for ext in [".m3u", ".m3u8", ".txt"]) and "ppsll" not in lower_url:
            print(f"      💡 检测到直连明文直播源订阅，已直接注入解析队列...")
            if main_url not in seen_source_urls:
                seen_source_urls.add(main_url)
                combined_lives.append({"name": f"直连源_{idx}", "url": main_url})
            continue
            
        # 兼容策略 2：针对未知或原版主配置进行自适应探测
        try:
            resp = requests.get(main_url, headers=headers, timeout=15)
            resp.raise_for_status()
            encoded = resp.text.strip()
            
            is_base64_json = False
            # 尝试作为原版加密 JSON 串进行解码
            if "#EXTM3U" not in encoded and "," not in encoded:
                try:
                    pad_encoded = encoded
                    if len(pad_encoded) % 4 != 0: 
                        pad_encoded += '=' * (4 - len(pad_encoded) % 4)
                    # 强行使用 ASCII 编码格式进行 base64 安全测试
                    decoded_bytes = base64.b64decode(pad_encoded.encode('ascii'))
                    data = json.loads(decoded_bytes.decode('utf-8'))
                    lives = data.get("lives", [])
                    print(f"      🔓 成功解密加密主配置，获取到 {len(lives)} 个子订阅源。")
                    for live in lives:
                        l_url = live.get("url")
                        if l_url and l_url not in seen_source_urls:
                            seen_source_urls.add(l_url)
                            combined_lives.append(live)
                    is_base64_json = True
                except Exception:
                    pass # 尝试解密失败，继续向下走明文探路检测
            
            # 如果不是加密 JSON，且包含明文 M3U/TXT 的核心特征，则自动作为直连源接入
            if not is_base64_json:
                if "#EXTM3U" in encoded or "," in encoded or "http" in encoded:
                    print(f"      💡 该链接返回明文文本数据，已自动将其本身适配为直播订阅源...")
                    if main_url not in seen_source_urls:
                        seen_source_urls.add(main_url)
                        combined_lives.append({"name": f"直连明文源_{idx}", "url": main_url})
                else:
                    raise ValueError("未知内容格式（既非合规 Base64 加密流，也无明文直播源特征）")
                    
        except Exception as e:
            print(f"   ⚠️ 该配置源加载或解析失败, 自动跳过. 错误原因: {e}")
            
    print(f"✅ Step 1 完成：全量配置检索完毕，共合并聚合 {len(combined_lives)} 个去重后的直播订阅数据源。")
    return combined_lives

def step2_parse_and_evict_dead_links(lives_list):
    print("[Step 2] 正在拉取各源站点并进行基础死链初筛...")
    raw_channels = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    def fetch_content(source):
        src_url = source.get("url", "")
        if not src_url:
            return []

        try:
            r = requests.get(src_url, headers=headers, timeout=12)
            if r.status_code == 200:
                return parse_text_to_list(r.content.decode('utf-8', errors='ignore'))
        except:
            pass

        return []

    def parse_text_to_list(content):
        extracted = []
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        is_m3u = any(line.startswith("#EXTINF") for line in lines[:20])

        if is_m3u:
            for i in range(len(lines)):
                if lines[i].startswith("#EXTINF:"):
                    try:
                        name = lines[i].split(",")[-1].strip()
                        if i + 1 < len(lines) and lines[i + 1].startswith("http"):
                            extracted.append({
                                "raw_name": heal_mojibake(name),
                                "url": lines[i + 1].strip()
                            })
                    except:
                        pass
        else:
            for line in lines:
                if "#genre#" in line:
                    continue

                if "," in line and "http" in line:
                    try:
                        parts = line.split(",", 1)
                        extracted.append({
                            "raw_name": heal_mojibake(parts[0].strip()),
                            "url": parts[1].strip()
                        })
                    except:
                        pass

        return extracted

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_content, s) for s in lives_list]

        total_sources = len(futures)

        for idx, f in enumerate(as_completed(futures), 1):
            result = f.result()
            raw_channels.extend(result)

            print(
                f"   [Step2-订阅拉取] "
                f"已完成 {idx}/{total_sources} 个源，"
                f"新增 {len(result)} 条，"
                f"累计 {len(raw_channels)} 条"
            )

    print(f"   已初步合并提取到 {len(raw_channels)} 条未过滤源。接入纠正库预洗...")
    raw_channels = execute_link_correction_and_blacklist(raw_channels)

    before_dedup_count = len(raw_channels)

    # URL排重（仅保留首次出现的URL）
    seen_urls = set()
    dedup_channels = []

    for ch in raw_channels:
        url = ch.get("url", "")

        if url and url not in seen_urls:
            seen_urls.add(url)
            dedup_channels.append(ch)

    raw_channels = dedup_channels

    print(
        f"   [Step2-URL排重] "
        f"排重前 {before_dedup_count} 条，"
        f"排重后 {len(raw_channels)} 条，"
        f"减少 {before_dedup_count - len(raw_channels)} 条"
    )

    for ch in raw_channels:
        name_lower = ch["raw_name"].lower().replace(" ", "")
        ch["is_hktw_pre"] = (
            any(k.lower() in name_lower for k in HK_TW_BRANDS)
            or any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
        )

    def check_alive_basic(item):
        is_hk = item.get("is_hktw_pre", False)
        cfg = HKTW_CONFIG if is_hk else MAINLAND_CONFIG

        try:
            with requests.get(
                item["url"],
                headers=PLAYER_HEADERS,
                timeout=(
                    cfg['connect_timeout_basic'],
                    cfg['read_timeout_basic']
                ),
                stream=True
            ) as r:

                if r.status_code in [200, 206] and \
                   'text/html' not in r.headers.get('Content-Type', '').lower():

                    try:
                        chunk = next(r.iter_content(chunk_size=512), None)

                        if chunk:
                            return item

                    except Exception as stream_err:
                        register_discard(
                            2,
                            f"建立连接后首包数据流严重超时僵死 (HTTP {r.status_code} | {type(stream_err).__name__})",
                            item["url"],
                            is_hktw=is_hk
                        )
                        return None

                register_discard(
                    2,
                    f"基础连通性握手失败 (HTTP {r.status_code})",
                    item["url"],
                    is_hktw=is_hk
                )

        except Exception as conn_err:
            register_discard(
                2,
                f"基础网络不可达或连接直接引发震荡崩溃 ({type(conn_err).__name__})",
                item["url"],
                is_hktw=is_hk
            )

        return None

    survived_channels = []

    with ThreadPoolExecutor(max_workers=20) as check_executor:
        futures = [check_executor.submit(check_alive_basic, ch) for ch in raw_channels]

        total_check = len(futures)
        checked_count = 0
        alive_count = 0

        for f in as_completed(futures):
            checked_count += 1

            res = f.result()

            if res:
                survived_channels.append(res)
                alive_count += 1

            if checked_count % 100 == 0 or checked_count == total_check:
                print(
                    f"   [Step2-活性检测] "
                    f"已检测 {checked_count}/{total_check} 条，"
                    f"存活 {alive_count} 条，"
                    f"淘汰 {checked_count - alive_count} 条"
                )

    print(f"✅ Step 2 完成：通过初筛活链共 {len(survived_channels)} 条。")
    return survived_channels

def step3_geo_ip_classify(channels):
    print("[Step 3] 开始检测 IP 归属地，划分国内组与港台组...")
    domestic_group = []
    hktw_group = []
    
    unique_urls = list(set(ch["url"] for ch in channels))
    url_to_ip = {}
    unique_ips = set()
    
    def resolve_dns(u):
        try:
            hostname = urlparse(u).hostname
            if hostname: return u, socket.gethostbyname(hostname)
        except: pass
        return u, None

    with ThreadPoolExecutor(max_workers=40) as dns_executor:
        futures = [dns_executor.submit(resolve_dns, u) for u in unique_urls]
        for f in as_completed(futures):
            u, ip = f.result()
            if ip:
                url_to_ip[u] = ip
                unique_ips.add(ip)

    ip_to_country = {}
    unique_ips_list = list(unique_ips)
    for i in range(0, len(unique_ips_list), 100):
        batch = unique_ips_list[i:i+100]
        try:
            response = requests.post("http://ip-api.com/batch?fields=status,countryCode,query", json=batch, timeout=12)
            if response.status_code == 200:
                for item in response.json():
                    if item.get("status") == "success":
                        ip_to_country[item.get("query")] = item.get("countryCode")
        except: pass
        time.sleep(0.5)

    for ch in channels:
        name_lower = ch["raw_name"].lower().replace(" ", "")
        is_hk_tw = any(k.lower() in name_lower for k in HK_TW_BRANDS) or any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
        
        if is_hk_tw:
            hktw_group.append(ch)
        else:
            ip = url_to_ip.get(ch["url"])
            if ip:
                country = ip_to_country.get(ip, "CN")
                if country != "CN": 
                    register_discard(3, f"非中国大陆IP归属地遭强制拦截 ({country})", ch["url"], is_hktw=False)
                    continue
            domestic_group.append(ch)
             
    print(f"✅ Step 3 完成：国内组分配 {len(domestic_group)} 条，港台组分配 {len(hktw_group)} 条。")
    return domestic_group, hktw_group

def step4_process_domestic_names(domestic_group):
    print("[Step 4] 正在净化规范国内组频道名称...")
    processed_domestic = []
    LOCAL_CHANNEL_KEYWORDS = [
        "都市", "民生", "新闻", "生活", "影视", "法治", "经济", "公共", "科教", "戏曲", 
        "梨园", "文物宝库", "欢笑剧场", "都市频道", "民生频道", "动漫秀场", "全纪实", "乡村"
    ]
    
    for item in domestic_group:
        raw_name = item["raw_name"]
        name_lower = raw_name.lower().replace(" ", "")
        
        if len(name_lower) > 25 or any(k in name_lower for k in ["测试", "更新", "公告", "直播中", "暂留"]):
            register_discard(4, f"排除无意义测试或野号行 ({raw_name})", item["url"], is_hktw=False)
            continue
        
        name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|（.*?）', '', raw_name)
        name = re.sub(r'[_#\-\s\t｜|]', '', name).upper()
        name = name.replace("雙語", "").replace("双语", "").replace("高清", "").replace("FHD", "").replace("HD", "")
        name = convert_t2s(name)
        
        category = None
        if "华数爱上4K" in name:
            category = "4K超清"
            name = "华数爱上4K"
        elif "4K" in name or "8K" in name or "UHD" in name:
            category = "4K超清"
            if "CCTV" in name or "中央" in name:
                match = re.search(r'(?:CCTV|中央|央视)([1-9]\d*)', name)
                if match and match.group(1) in ["1", "13", "16"]:
                    name = f"CCTV-{match.group(1)} {STANDARD_CCTV.get(match.group(1), '')} 4K"
                else:
                    name = "CCTV 4K 超高清"
            else:
                for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
                    if std_wei.replace("卫视", "") in name:
                        name = f"{std_wei} 4K"
                        break
        elif any(re.search(p, name_lower) for p in [r'cctv-?([1-9]|1[0-7])', r'中央([1-9]|1[0-7])[套频]', r'央视([1-9]|1[0-7])[套频]', r'cctv([1-9]|1[0-7])', r'cctv-?5\+']):
            category = "央视频道"
            match = re.search(r'(?:CCTV|中央|央视|中央电视台)([1-9]\d*\+?|[1-9])', name)
            if match:
                num = match.group(1)
                if num == "5+": name = "CCTV-5+ 体育赛事"
                elif num in STANDARD_CCTV: name = f"CCTV-{num} {STANDARD_CCTV[num]}"
            if "5+" in name: name = "CCTV-5+ 体育赛事"
        else:
            is_matched_wei = False
            for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
                short_name = std_wei.replace("卫视", "").replace("卡通", "").replace("少儿", "")
                if any(kw in name for kw in LOCAL_CHANNEL_KEYWORDS): continue
                if re.search(rf"{short_name}\d+", name): continue
                if (name == std_wei) or (std_wei in name) or (name == short_name):
                    category = "卫视频道"
                    name = std_wei
                    is_matched_wei = True
                    break
                    
        if category:
            processed_domestic.append({"category": category, "name": name, "url": item["url"]})
        else:
            register_discard(4, f"未命中核心白名单规范字典归类 (判定为地方台或杂牌源: {raw_name})", item["url"], is_hktw=False)
    return processed_domestic

def step5_process_hktw_names(hktw_group):
    print("[Step 5] 正在净化规范港台组频道名称...")
    processed_hktw = []
    LOCAL_HKTW_CHANNELS = [
        "中天新闻", "中天综合", "中天亚洲", "凤凰资讯", "凤凰卫视", "凤凰中文", "凤凰香港",
        "TVBS新闻", "TVBS欢乐台", "TVBS", "东森新闻", "东森电影", "东森综合", "东森洋片", "东森戏剧", "东森幼幼",
        "纬来日本", "纬来体育", "纬来电影", "纬来综合", "纬来戏剧", "纬来育乐", "年代新闻", "非凡新闻", "非凡商业",
        "三立新闻", "三立台湾", "三立都会", "三立综合", "民视新闻", "民视第一台", "民视台湾台", "民视",
        "台视新闻", "台视", "中视新闻", "中视", "华视新闻", "华视", "公视", "翡翠台", "明珠台", "ViuTV", "HOY TV",
        "HBO HITS", "HBO FAMILY", "HBO SIGNATURE", "HBO", "AXN", "FOX", "DISCOVERY", "国家地理", "动物星球"
    ]
    
    for item in hktw_group:
        raw_name = item["raw_name"]
        name_lower = raw_name.lower().replace(" ", "")
        
     #   if len(name_lower) > 25 or any(k in name_lower for k in ["测试", "更新", "公告", "直播中", "暂留"]):
     #       continue
        if len(name_lower) > 25 or any(k in name_lower for k in ["测试", "更新", "公告", "直播中", "暂留", "购", "经典香港电影", "财经", "香港综合"]):
            register_discard(4, f"排除无意义测试或野号行 ({raw_name})", item["url"], is_hktw=False)
            continue
          
        name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|（.*?）', '', raw_name)
        name = re.sub(r'[_#\-\s\t｜|]', '', name).upper()
        name = name.replace("雙語", "").replace("双语", "").replace("高清", "").replace("FHD", "").replace("HD", "").replace("4GTV", "").replace("备", "").replace("TVB功夫台", "TVB亚洲武俠").replace("AMC电影台", "AMC电影")
        name = convert_t2s(name)
        
        category = "港台频道"
        sorted_hktw_channels = sorted(LOCAL_HKTW_CHANNELS, key=len, reverse=True)
        for std_hk in sorted_hktw_channels:
            if std_hk in name:
                name = std_hk
                break  
        processed_hktw.append({"category": category, "name": name, "url": item["url"]})
    return processed_hktw

def step6_stability_check(url, cfg, is_hktw):
    is_4k_url = any(k in url.lower() for k in ["4k", "uhd", "239.252.220.212", "239.3.1.236"]) 
    connect_timeout = 8 if is_hktw else 5
    read_timeout = cfg['timeout_stable']
    
    try:
        with requests.get(url, headers=PLAYER_HEADERS, timeout=(connect_timeout, read_timeout), stream=True) as r:
            if r.status_code not in [200, 206]: 
                register_discard(6, f"测速响应低保线建立失败 (HTTP {r.status_code})", url, is_hktw)
                return False
            
            start_time = time.time()
            total_bytes = 0
            last_chunk_time = start_time
            max_jitter = 0  
            
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk: break
                current_time = time.time()
                jitter = current_time - last_chunk_time
                if jitter > max_jitter: max_jitter = jitter
                total_bytes += len(chunk)
                last_chunk_time = current_time
                if (current_time - start_time) > read_timeout: break
            
            duration = time.time() - start_time
            if duration <= 0: return False
            avg_speed = total_bytes / duration
            
            if max_jitter > cfg['max_jitter_dead'] or avg_speed < cfg['min_speed_dead']:
                register_discard(6, f"触发网络生死线 (最大网络抖动:{max_jitter:.1f}s, 下载速:{avg_speed/1024:.1f}KB/s)", url, is_hktw)
                return False

            if is_4k_url:
                if max_jitter > 2.5 or avg_speed < 300 * 1024:
                    register_discard(6, f"4K超高规格带宽门槛未达标 (流速:{avg_speed/1024:.1f}KB/s)", url, is_hktw)
                    return False
                return True  

            if max_jitter > cfg['max_jitter_normal'] or avg_speed < cfg['min_speed_normal']:
                register_discard(6, f"网络稳定性丢包震荡超标放行拒绝 (平均速率:{avg_speed/1024:.1f}KB/s)", url, is_hktw)
                return False
            return True  
    except Exception as e:
        register_discard(6, f"拉流阶段网络极度超时或震荡断链 ({type(e).__name__})", url, is_hktw)
        return False

def step7_8_ffmpeg_pipeline_audit(item, cfg, is_hktw):
### url 改成了item
    url = item["url"]
    ### 新加的
    category = item.get("category", "")    
    ### 新加的
    # url 修改为 item
    FFMPEG_BIN = '/root/ffmpeg' if os.path.exists('/root/ffmpeg') else 'ffmpeg'
    timeout_str = str(int(cfg['timeout_video'] * 1000000))
    
    cmd = [
        FFMPEG_BIN, '-y', '-rw_timeout', timeout_str, 
        '-i', url, '-vframes', '30', 
        '-vf', 'cropdetect=limit=32:round=2', 
        '-f', 'null', '-'
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=cfg['timeout_video'])
        if res.returncode != 0:
            register_discard(8, f"FFmpeg解码返回崩溃指令状态码 ({res.returncode})", url, is_hktw)
            return False
        stderr_output = res.stderr
        
        video_line = None
        for line in stderr_output.split('\n'):
            if 'Stream #' in line and 'Video:' in line:
                video_line = line
                break
        if not video_line:
            register_discard(7, "无法成功剥离解析出Video视讯轨道元数据", url, is_hktw)
            return False
            
        width, height = 0, 0
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', video_line)
        if res_match:
            width = int(res_match.group(1))
            height = int(res_match.group(2))
            
            # 4K频道真实分辨率校验
            if category == "4K超清":
                if height < 2160:
                    register_discard(
                    7,
                    f"伪4K频道 ({width}x{height})",
                    url,
                    is_hktw
                )
                return False
           ### 结束  
        if height < cfg['min_height']:
            register_discard(7, f"画质低劣物理降维打击 (实测分辨率为: {width}x{height} < {cfg['min_height']}p)", url, is_hktw)
            return False

        if "frame=" not in stderr_output:
            register_discard(8, "黑屏僵尸源拦截 (未捕获到任何有效图像输出帧 frame=)", url, is_hktw)
            return False
            
        speed_all = re.findall(r'speed=\s*([\d\.]+)x', stderr_output)
        if speed_all:
            try:
                speed_val = float(speed_all[-1])  
                if speed_val < cfg['min_speed_ratio']:
                    register_discard(8, f"解码传输速率倒挂判定为严重丢帧幻灯片 (最终speed: {speed_val}x < {cfg['min_speed_ratio']}x)", url, is_hktw)
                    return False
            except ValueError: pass
                
        zombie_keywords = {
            "PPS id out of range": "破损NAL控制集画面一闪即黑", 
            "Error parsing NAL unit": "NAL单元破损碎裂无法持续渲染", 
            "Could not find ref with POC": "基础P/B参考帧丢失导致画面持续黑屏",
            "corrupt decoded frame": "下发数据大面积损坏画面严重花屏闪烁"
        }
        for kw, desc in zombie_keywords.items():
            if kw in stderr_output:
                register_discard(8, f"流式解析致命画质损伤报错 ({desc})", url, is_hktw)
                return False
                
        crop_lines = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr_output)
        if crop_lines and width > 0 and height > 0:
            crop_w, crop_h, _, _ = map(int, crop_lines[-1])
            if (width - crop_w) > 24 or (height - crop_h) > 24:
                register_discard(8, f"黑边裁剪边缘严重超缩进判定为劣质边框源", url, is_hktw)
                return False
        return True
    except Exception as e:
        register_discard(8, f"底层分析管道发生意外瘫痪性崩溃 ({type(e).__name__})", url, is_hktw)
        return False

def step9_generate_domestic_and_upload(domestic_list):
    print("[Step 9] 正在生成最终国内组 live.m3u 并唤醒同步脚本...")
    def get_cctv_key(n):
        if "5+" in n: return 5.5
        m = re.search(r'CCTV-(\d+)', n)
        return int(m.group(1)) if m else 100
    def get_pinyin_key(n):
        p_map = {"安":"A","北":"B","重":"C","东":"D","广":"G","甘":"G","贵":"G","湖":"H","河":"H","黑":"H","海":"H","江":"J","吉":"J","金":"J","卡":"K","辽":"L","宁":"N","青":"Q","山":"S","深":"S","四":"S","三":"S","天":"T","厦":"X","新":"X","西":"X","云":"Y","浙":"Z"}
        return f"{p_map.get(n[0], 'Z')}_{n}"

    grouped = defaultdict(lambda: defaultdict(list))
    for item in domestic_list:
        grouped[item["category"]][item["name"]].append(item["url"])
        
    m3u_lines = ["#EXTM3U", f"# Update: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
    for cat in ["4K超清", "央视频道", "卫视频道"]:
        channels = list(grouped[cat].keys())
        if not channels: continue
        if cat == "央视频道": channels.sort(key=get_cctv_key)
        elif cat == "卫视频道": channels.sort(key=get_pinyin_key)
        else: channels.sort()
        
        m3u_lines.append(f"\n# --- {cat} ---")
        for name in channels:
            urls = list(dict.fromkeys(grouped[cat][name]))
            migu = [u for u in urls if "miguvideo.com" in u or "cmvideo.cn" in u]
            others = [u for u in urls if u not in migu]
            for url in (migu + others):
                m3u_lines.append(f'#EXTINF:-1 group-title="{cat}",{name}')
                m3u_lines.append(url)
                
    with open("./live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    print("   -> 国内包已保存至当前目录下的 live.m3u")
        
    upload_script = "/root/upload.sh"
    if os.path.exists(upload_script):
        os.chmod(upload_script, 0o755)
        subprocess.run([upload_script])
        print("   -> 外部 upload.sh 脚本同步唤醒完成。")

def step10_generate_hktw_local(hktw_list):
    print("[Step 10] 正在生成本地港台专用包 gt.m3u ...")
    grouped = defaultdict(list)
    for item in hktw_list:
        grouped[item["name"]].append(item["url"])
         
    m3u_lines = ["#EXTM3U", f"# Update: {time.strftime('%Y-%m-%d %H:%M:%S')} (港台直通无过滤版)"]
    names = sorted(list(grouped.keys()))
    if names:
        m3u_lines.append("\n# --- 港台频道 ---")
        for name in names:
            urls = list(dict.fromkeys(grouped[name]))
            for url in urls:
                m3u_lines.append(f'#EXTINF:-1 group-title="港台频道",{name}')
                m3u_lines.append(url)
                
    with open("./gt.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    print("✅ Step 10 完成：完整港台包已保存至当前目录下的 gt.m3u。")

# ==================== 🕹️ 主程序全局分流引擎 ====================
def main():
    # 动态把合并的多源列表送入重构后的 Step 1 引擎
    lives = step1_fetch_all_configs(CONFIG_SOURCES)
    if not lives: 
        print("❌ 所有的订阅配置源抓取解析均失败，请检查网络或源有效性。")
        return
    
    survived_links = step2_parse_and_evict_dead_links(lives)
    if not survived_links: return
    
    domestic_raw, hktw_raw = step3_geo_ip_classify(survived_links)
    domestic_cleaned = step4_process_domestic_names(domestic_raw)
    
    hktw_cleaned = step5_process_hktw_names(hktw_raw)
    
    final_domestic_list = []
    
    def run_quality_pipeline(item, is_hktw):
        url = item["url"]
        cfg = HKTW_CONFIG if is_hktw else MAINLAND_CONFIG
        if not step6_stability_check(url, cfg, is_hktw): return None
        ### url修改为 item
        if not step7_8_ffmpeg_pipeline_audit(item, cfg, is_hktw): return None
        return item

    print(f"\n⚡ 进入并发质量流水线段：层层卡点严控中 (线程数: {MAX_WORKERS})...")
    
    if domestic_cleaned:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as dom_executor:
            futures = {dom_executor.submit(run_quality_pipeline, item, False): item for item in domestic_cleaned}
            for f in as_completed(futures):
                res = f.result()
                if res: final_domestic_list.append(res)

    print(f"📊 检测结束：国内组通过卡点共 {len(final_domestic_list)} 条，港台组（直通直出）共 {len(hktw_cleaned)} 条。")

    step9_generate_domestic_and_upload(final_domestic_list)
    step10_generate_hktw_local(hktw_cleaned)
    
    print("\n📝 正在将全量各拦截点被斩断的【国内组】无用直播源导出至当前目录下的 discard_report.txt ...")
    sorted_steps_dom = sorted(list(discard_registry_domestic.keys()))
    with open("./discard_report.txt", "w", encoding="utf-8") as rf:
        for step_header in sorted_steps_dom:
            rf.write(f"{step_header}\n")
            for url in discard_registry_domestic[step_header]:
                rf.write(f"{url}\n")
            rf.write("\n")  
            
    print("🎉 港台双参数外置解耦重构审计版运行结束。港台源已全量直通导出。")

if __name__ == "__main__":
    main()