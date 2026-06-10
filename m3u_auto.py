#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直播源质量审计系统 (港台直通无阻多源兼容版)
优化版本：修复bug + 自动学习黑名单(set O(1)查找) + 4K分辨率严格卡控 + 港台-11放行 + 合并输出 + 自定义直播源
业务逻辑完全不变
"""

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
import logging
from urllib.parse import urlparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

print("=== 直播源质量审计系统 (港台直通无阻多源兼容版) ===")

CONFIG_FILE_PATH = "./config.json"
AUTO_BLACKLIST_FILE = "./auto_blacklist.json"

# ==================== ⚙️ 出厂默认配置数据区 ====================
DEFAULT_MAINLAND_CONFIG = {
    'timeout_video': 20.0,
    'timeout_stable': 5.0,
    'connect_timeout_basic': 6,
    'read_timeout_basic': 4,
    'min_speed_dead': 100 * 1024,
    'max_jitter_dead': 3.0,
    'min_speed_normal': 180 * 1024,
    'max_jitter_normal': 2.0,
    'min_height': 720,
    'min_speed_ratio': 0.8,
    'connect_timeout_stable': 5,
    'allow_low_ratio': False,
    'strict_zombie_check': True,
    'strict_frame_check': True,
    'max_black_border': 24,
    'min_speed_4k': 300 * 1024,
    'max_jitter_4k': 2.5
}

DEFAULT_HKTW_CONFIG = {
    'timeout_video': 30.0,
    'timeout_stable': 8.0,
    'connect_timeout_basic': 10,
    'read_timeout_basic': 6,
    'min_speed_dead': 60 * 1024,
    'max_jitter_dead': 5.0,
    'min_speed_normal': 100 * 1024,
    'max_jitter_normal': 4.0,
    'min_height': 480,
    'min_speed_ratio': 0.5,
    'connect_timeout_stable': 8,
    'allow_low_ratio': True,
    'strict_zombie_check': False,
    'strict_frame_check': False,
    'max_black_border': 60,
    'min_speed_4k': 100 * 1024,
    'max_jitter_4k': 5.0
}

DEFAULT_HK_TW_BRANDS = [
    "凤凰", "鳳凰", "TVB", "翡翠台", "翡翠臺", "明珠台", "明珠臺",
    "东森", "東森", "中天", "纬来", "緯來", "三立", "八大", "年代",
    "非凡", "华视", "華視", "台视", "臺視", "民视", "民視", "公视", "公視",
    "中视", "中視", "TVBS", "靖天", "靖洋", "寰宇", "美亚", "美亞",
    "影迷数位", "影迷數位", "AMC", "香港卫视", "香港衛視",
    "HBO", "AXN", "FOX", "DISCOVERY", "国家地理", "动物星球", "VIUTV", "HOY TV",
    "澳视", "澳視", "澳门", "澳門", "莲花", "蓮花",
    "东森幼幼", "爱尔达", "愛爾達", "博斯", "龙华", "龍華", "好萊塢電影台", "好莱坞电影台",
    "有线", "有線", "卫视电影", "衛視電影","華纳电视","华纳电视",
    "BBC", "CNN", "NHK", "KBS", "TVN", "Animax", "Cartoon","AXN",
    "星卫", "星衛", "华纳", "華納", "Cinemax",
]

DEFAULT_CONFIG_SOURCES = [
    "https://ppsll.cc.cd/ppsll",
]

VOD_EXTENSIONS = [".mp4", ".mkv", ".avi", ".rmvb", ".flv", ".mov", ".wmv", ".webm"]

# ==================== 自动学习黑名单引擎 ====================
_pending_blacklist = set()
_pending_blacklist_lock = threading.Lock()
_loaded_blacklist = None

# 优化：只拦截Step 2中真正网络不可达或明确HTTP致命状态码的永久错误
PERMANENT_FAILURE_KEYWORDS = [
    "Step2", "HTTP 403", "HTTP 404", "HTTP 410", "HTTP403", "HTTP404", "HTTP410",
    "Connection refused", "Connection reset", "ConnectionError",
    "Name or service not known", "No address associated"
]


def load_auto_blacklist():
    global _loaded_blacklist
    if _loaded_blacklist is not None:
        return _loaded_blacklist
    if os.path.exists(AUTO_BLACKLIST_FILE):
        try:
            with open(AUTO_BLACKLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _loaded_blacklist = set(data.get("urls", []))
                return _loaded_blacklist
        except Exception:
            pass
    _loaded_blacklist = set()
    return _loaded_blacklist


def add_to_auto_blacklist(url, fail_reason=""):
    if not url:
        return
    is_permanent = any(kw in fail_reason for kw in PERMANENT_FAILURE_KEYWORDS)
    if not is_permanent:
        return
    with _pending_blacklist_lock:
        _pending_blacklist.add(url)


def flush_auto_blacklist():
    global _loaded_blacklist
    old = load_auto_blacklist()
    merged = old | _pending_blacklist
    try:
        with open(AUTO_BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"urls": sorted(list(merged))}, f, indent=2, ensure_ascii=False)
        _loaded_blacklist = merged
        return merged
    except Exception as e:
        print(f"   ⚠️ 保存自动黑名单失败: {e}")
        return old


def is_in_auto_blacklist(url):
    if not url:
        return False
    with _pending_blacklist_lock:
        if url in _pending_blacklist:
            return True
    return url in load_auto_blacklist()


# ==================== 配置加载 ====================
def load_or_create_user_config():
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"💡 未检测到本地配置，正在为您自动生成个性化模板: {CONFIG_FILE_PATH}")
        factory_data = {
            "MAINLAND_CONFIG": DEFAULT_MAINLAND_CONFIG,
            "HKTW_CONFIG": DEFAULT_HKTW_CONFIG,
            "HK_TW_BRANDS": DEFAULT_HK_TW_BRANDS,
            "CONFIG_SOURCES": DEFAULT_CONFIG_SOURCES,
            "CORRECTION_DB": [],
            "CUSTOM_CHANNELS": []
        }
        try:
            with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(factory_data, f, indent=2, ensure_ascii=False)
            print("   -> 默认出厂配置模版生成成功！")
        except Exception as e:
            print(f"⚠️ 写入配置文件失败: {e}")
        return (DEFAULT_MAINLAND_CONFIG, DEFAULT_HKTW_CONFIG,
                DEFAULT_HK_TW_BRANDS, DEFAULT_CONFIG_SOURCES, [], [])
    else:
        print(f"🚀 检测到个性化配置文件，正在加载...")
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                user_data = json.load(f)
            m_cfg = DEFAULT_MAINLAND_CONFIG.copy()
            m_cfg.update(user_data.get("MAINLAND_CONFIG", {}))
            h_cfg = DEFAULT_HKTW_CONFIG.copy()
            h_cfg.update(user_data.get("HKTW_CONFIG", {}))
            brands = user_data.get("HK_TW_BRANDS", DEFAULT_HK_TW_BRANDS)
            sources = user_data.get("CONFIG_SOURCES", DEFAULT_CONFIG_SOURCES)
            correction_db = user_data.get("CORRECTION_DB", [])
            custom_channels = user_data.get("CUSTOM_CHANNELS", [])
            print("   -> 成功加载个性化配置")
            return m_cfg, h_cfg, brands, sources, correction_db, custom_channels
        except Exception as e:
            print(f"❌ 解析 config.json 失败: {e}，使用默认参数")
            return (DEFAULT_MAINLAND_CONFIG, DEFAULT_HKTW_CONFIG,
                    DEFAULT_HK_TW_BRANDS, DEFAULT_CONFIG_SOURCES, [], [])


MAINLAND_CONFIG, HKTW_CONFIG, HK_TW_BRANDS, CONFIG_SOURCES, CORRECTION_DB, CUSTOM_CHANNELS = load_or_create_user_config()

auto_blacklist = load_auto_blacklist()
print(f"📚 自动学习黑名单已加载: {len(auto_blacklist)} 条URL")
print(f"⭐ 自定义直播源已加载: {len(CUSTOM_CHANNELS)} 个频道")

# ==================== 其余静态核心字典区 ====================
MAX_WORKERS = 3

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

# ==================== 丢弃审计追踪 ====================
discard_lock = threading.Lock()
discard_registry_domestic = defaultdict(list)


def register_discard(step_num, reason, url, is_hktw=False):
    if is_hktw:
        return
    header = f"====丢弃步骤{step_num}  {reason}  ======="
    with discard_lock:
        if url not in discard_registry_domestic[header]:
            discard_registry_domestic[header].append(url)


# ==================== 基础文本净化 ====================
def heal_mojibake(text):
    if not text:
        return ""
    mojibake_features = ['闋', '槌', '嚢', '涓', '鏂', '闆', '褰', '璺', '缈', '繝', '鐛', '嗃', '鑿']
    if any(f in text for f in mojibake_features):
        try:
            recovered = text.encode('gbk', errors='ignore').decode('utf-8', errors='ignore')
            if recovered and not any(f in recovered for f in mojibake_features):
                return recovered
        except:
            pass
    return text


def convert_t2s(text):
    if not text:
        return ""
    return "".join(TRADITIONAL_TO_SIMPLIFIED.get(char, char) for char in text)


# ==================== 纠正库处理 ====================
def execute_link_correction_and_blacklist(raw_channels):
    cleaned_channels = []
    discard_count = 0
    rename_count = 0
    auto_blacklist_count = 0
    vod_discard_count = 0
    correction_discard_count = 0

    for item in raw_channels:
        url = item.get("url", "")
        raw_name = item.get("raw_name", "")
        if not url:
            continue

        # 仅在此处由Step 2拉取数据时，检查自动黑名单
        if is_in_auto_blacklist(url):
            register_discard(1, "自动学习黑名单拦截", url, is_hktw=False)
            auto_blacklist_count += 1
            discard_count += 1
            continue

        url_lower_no_params = url.lower().split("?")[0]
        if any(url_lower_no_params.endswith(ext) for ext in VOD_EXTENSIONS):
            register_discard(1, "非直播源(点播文件)全局拦截", url, is_hktw=False)
            vod_discard_count += 1
            discard_count += 1
            continue

        is_discarded = False
        current_name = raw_name

        for rule in CORRECTION_DB:
            match_target = rule["match"]
            action = rule["action"]
            if action == "discard" and (match_target in url):
                name_lower = raw_name.lower().replace(" ", "")
                is_hk = any(k.lower() in name_lower for k in HK_TW_BRANDS) or \
                        any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
                if not is_hk:
                    register_discard(1, f"纠正库黑名单拦截 (命中: {match_target})", url, is_hktw=False)
                is_discarded = True
                correction_discard_count += 1
                discard_count += 1
                break
            elif action == "rename" and (match_target == url):
                current_name = rule["value"]
                rename_count += 1

        if not is_discarded:
            item["raw_name"] = current_name
            cleaned_channels.append(item)

    print(f"   [🧠 黑名单拦截报告] 自动学习: {auto_blacklist_count} 条, "
          f"点播文件: {vod_discard_count} 条, "
          f"CORRECTION_DB: {correction_discard_count} 条, "
          f"改名: {rename_count} 条。")
    return cleaned_channels


# ==================== 核心步骤 ====================
def step1_fetch_all_configs(urls_list):
    print("[Step 1] 正在智能抓取并解析多源主配置...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    combined_lives = []
    seen_source_urls = set()

    for idx, main_url in enumerate(urls_list, 1):
        print(f"   -> 正在加载 ({idx}/{len(urls_list)}): {main_url}")
        lower_url = main_url.lower()
        if any(ext in lower_url for ext in [".m3u", ".m3u8", ".txt"]) and "ppsll" not in lower_url:
            print(f"      💡 检测到直连明文直播源订阅，已直接注入解析队列...")
            if main_url not in seen_source_urls:
                seen_source_urls.add(main_url)
                combined_lives.append({"name": f"直连源_{idx}", "url": main_url})
            continue

        try:
            resp = requests.get(main_url, headers=headers, timeout=15)
            resp.raise_for_status()
            encoded = resp.text.strip()
            is_base64_json = False
            if "#EXTM3U" not in encoded and "," not in encoded:
                try:
                    pad_encoded = encoded
                    if len(pad_encoded) % 4 != 0:
                        pad_encoded += '=' * (4 - len(pad_encoded) % 4)
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
                    pass
            if not is_base64_json:
                if "#EXTM3U" in encoded or "," in encoded or "http" in encoded:
                    print(f"      💡 该链接返回明文文本数据，已自动将其本身适配为直播订阅源...")
                    if main_url not in seen_source_urls:
                        seen_source_urls.add(main_url)
                        combined_lives.append({"name": f"直连明文源_{idx}", "url": main_url})
                else:
                    raise ValueError("未知内容格式")
        except Exception as e:
            print(f"   ⚠️ 该配置源加载或解析失败, 自动跳过. 错误原因: {e}")

    print(f"✅ Step 1 完成：共合并聚合 {len(combined_lives)} 个直播订阅数据源。")
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
            r = requests.get(src_url, headers=headers, timeout=20)
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
                            extracted.append({"raw_name": heal_mojibake(name), "url": lines[i + 1].strip()})
                    except:
                        pass
        else:
            for line in lines:
                if "#genre#" in line:
                    continue
                if "," in line and "http" in line:
                    try:
                        parts = line.split(",", 1)
                        extracted.append({"raw_name": heal_mojibake(parts[0].strip()), "url": parts[1].strip()})
                    except:
                        pass
        return extracted

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_content, s) for s in lives_list]
        total_sources = len(futures)
        for idx, f in enumerate(as_completed(futures), 1):
            result = f.result()
            raw_channels.extend(result)
            print(f"   [Step2-订阅拉取] 已完成 {idx}/{total_sources} 个源，新增 {len(result)} 条，累计 {len(raw_channels)} 条")

    print(f"   已初步合并提取到 {len(raw_channels)} 条未过滤源。接入纠正库预洗...")
    raw_channels = execute_link_correction_and_blacklist(raw_channels)

    before_dedup_count = len(raw_channels)
    seen_urls = set()
    dedup_channels = []
    for ch in raw_channels:
        url = ch.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            dedup_channels.append(ch)
    raw_channels = dedup_channels
    print(f"   [Step2-URL排重] 排重前 {before_dedup_count} 条，排重后 {len(raw_channels)} 条")

    for ch in raw_channels:
        name_lower = ch["raw_name"].lower().replace(" ", "")
        ch["is_hktw_pre"] = (
            any(k.lower() in name_lower for k in HK_TW_BRANDS)
            or any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
        )

    def check_alive_basic(item):
        is_hk = item.get("is_hktw_pre", False) or item.get("is_hktw", False)
        cfg = HKTW_CONFIG if is_hk else MAINLAND_CONFIG
        connect_to = cfg.get('connect_timeout_basic', 6) + (8 if is_hk else 0)
        read_to = cfg.get('read_timeout_basic', 4) + (6 if is_hk else 0)
        try:
            with requests.get(item["url"], headers=PLAYER_HEADERS,
                              timeout=(connect_to, read_to), stream=True) as r:
                if r.status_code in [200, 206]:
                    try:
                        chunk = next(r.iter_content(chunk_size=1024), None)
                        if chunk:
                            return item
                        else:
                            if is_hk:
                                print(f"   [宽松放行] 港台源 {item.get('raw_name')} 首包为空但状态正常")
                                return item
                    except:
                        if is_hk:
                            print(f"   [宽松放行] 港台源 {item.get('raw_name')} 首包读取异常但放行")
                            return item
                        else:
                            register_discard(2, "首包读取失败", item["url"], is_hktw=is_hk)
                            add_to_auto_blacklist(item["url"], "Step2-首包读取失败")  # 仅保留Step 2黑名单写入
                            return None
                if is_hk:
                    print(f"   [宽松放行] 港台源 {item.get('raw_name')} HTTP {r.status_code} 仍尝试保留")
                    return item
                register_discard(2, f"基础连通性握手失败 (HTTP {r.status_code})", item["url"], is_hktw=is_hk)
                add_to_auto_blacklist(item["url"], f"Step2-HTTP{r.status_code}")  # 仅保留Step 2黑名单写入
        except Exception as e:
            err_name = type(e).__name__
            if is_hk:
                if "Timeout" in err_name or "Connection" in err_name:
                    print(f"   [宽松放行] 港台源 {item.get('raw_name')} 超时仍保留")
                    return item
            register_discard(2, f"基础网络不可达 ({err_name})", item["url"], is_hktw=is_hk)
            add_to_auto_blacklist(item["url"], f"Step2-{err_name}")  # 仅保留Step 2黑名单写入
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
                print(f"   [Step2-活性检测] 已检测 {checked_count}/{total_check} 条，存活 {alive_count} 条")

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
            if hostname:
                return u, socket.gethostbyname(hostname)
        except:
            pass
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
        batch = unique_ips_list[i:i + 100]
        try:
            response = requests.post("http://ip-api.com/batch?fields=status,countryCode,query",
                                     json=batch, timeout=12)
            if response.status_code == 200:
                for item in response.json():
                    if item.get("status") == "success":
                        ip_to_country[item.get("query")] = item.get("countryCode")
        except:
            pass
        time.sleep(0.5)

    for ch in channels:
        name_lower = ch["raw_name"].lower().replace(" ", "")
        is_hk_tw = any(k.lower() in name_lower for k in HK_TW_BRANDS) or \
                   any(loc in name_lower for loc in ["香港", "台湾", "澳门", "澳門"])
        if is_hk_tw:
            hktw_group.append(ch)
        else:
            ip = url_to_ip.get(ch["url"])
            if ip:
                country = ip_to_country.get(ip, "CN")
                if country != "CN":
                    register_discard(3, f"非中国大陆IP归属地遭强制拦截 ({country})", ch["url"], is_hktw=False)
                    # 拔除此处的 add_to_auto_blacklist 避免连累同源其他有效名称
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
            # 拔除黑名单机制
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
        elif any(re.search(p, name_lower) for p in [
            r'cctv-?([1-9]|1[0-7])', r'中央([1-9]|1[0-7])[套频]',
            r'央视([1-9]|1[0-7])[套频]', r'cctv([1-9]|1[0-7])', r'cctv-?5\+'
        ]):
            category = "央视频道"
            match = re.search(r'(?:CCTV|中央|央视|中央电视台)([1-9]\d*\+?|[1-9])', name)
            if match:
                num = match.group(1)
                if num == "5+":
                    name = "CCTV-5+ 体育赛事"
                elif num in STANDARD_CCTV:
                    name = f"CCTV-{num} {STANDARD_CCTV[num]}"
            if "5+" in name:
                name = "CCTV-5+ 体育赛事"
        else:
            is_matched_wei = False
            for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
                short_name = std_wei.replace("卫视", "").replace("卡通", "").replace("少儿", "")
                if any(kw in name for kw in LOCAL_CHANNEL_KEYWORDS):
                    continue
                if re.search(rf"{short_name}\d+", name):
                    continue
                if (name == std_wei) or (std_wei in name) or (name == short_name):
                    category = "卫视频道"
                    name = std_wei
                    is_matched_wei = True
                    break
        if category:
            processed_domestic.append({"category": category, "name": name, "url": item["url"]})
        else:
            register_discard(4, f"未命中核心白名单规范字典归类 ({raw_name})", item["url"], is_hktw=False)
            # 拔除黑名单机制
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
        if len(name_lower) > 25 or any(k in name_lower for k in [
            "测试", "更新", "公告", "直播中", "暂留", "购", "经典香港电影", "财经", "香港综合",
            "購", "新闻", "新聞", "財經", "凤凰"
        ]):
            register_discard(4, f"排除无意义测试或野号行 ({raw_name})", item["url"], is_hktw=False)
            # 拔除黑名单机制
            continue

        name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|（.*?）', '', raw_name)
        name = re.sub(r'[_#\-\s\t｜|]', '', name).upper()
        name = name.replace("雙語", "").replace("双语", "").replace("高清", "").replace("FHD", "").replace("HD", "").replace("NICEBINGO", "").replace("NICETV", "")
        name = name.replace("4GTV", "").replace("备", "").replace("TVB功夫台", "TVB亚洲武俠")
        name = name.replace("AMC电影台", "AMC电影").replace("TVBJ", "TVBJ1")
        name = name.replace("TVBNEWS", "无线新闻台").replace("靖洋戏剧台", "靖洋戏剧")
        name = name.replace("靖天电影台", "靖天电影").replace("靖天戏剧台", "靖天戏剧")
        name = name.replace("香港C+", "美亚C+").replace("纬来精彩频道", "纬来精彩")
        name = name.replace("东森美洲卫视", "东森美洲").replace("TVB星河3", "TVB星河")
        name = name.replace("KLT靖天国际台", "靖天国际台").replace("Geo-blocked", "")
        name = name.replace("靖天电影台", "靖天电影")
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
    connect_timeout = cfg.get('connect_timeout_stable', 8 if is_hktw else 5)
    read_timeout = cfg.get('timeout_stable', 5.0)
    min_speed_4k = cfg.get('min_speed_4k', cfg.get('min_speed_dead', 100 * 1024))
    max_jitter_4k = cfg.get('max_jitter_4k', cfg.get('max_jitter_dead', 3.0))

    try:
        with requests.get(url, headers=PLAYER_HEADERS,
                         timeout=(connect_timeout, read_timeout), stream=True) as r:
            if r.status_code not in [200, 206]:
                register_discard(6, f"测速响应失败 (HTTP {r.status_code})", url, is_hktw)
                # 拔除黑名单学习
                return False

            start_time = time.time()
            total_bytes = 0
            last_chunk_time = start_time
            max_jitter = 0
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    break
                current_time = time.time()
                jitter = current_time - last_chunk_time
                if jitter > max_jitter:
                    max_jitter = jitter
                total_bytes += len(chunk)
                last_chunk_time = current_time
                if (current_time - start_time) > read_timeout:
                    break

            duration = time.time() - start_time
            if duration <= 0:
                return False
            avg_speed = total_bytes / duration

            max_jitter_dead = cfg.get('max_jitter_dead', 3.0)
            min_speed_dead = cfg.get('min_speed_dead', 100 * 1024)
            if max_jitter > max_jitter_dead or avg_speed < min_speed_dead:
                register_discard(6, f"生死线未达标 (抖动:{max_jitter:.1f}s, 速度:{avg_speed/1024:.1f}KB/s)", url, is_hktw)
                return False

            if is_4k_url:
                if max_jitter > max_jitter_4k or avg_speed < min_speed_4k:
                    register_discard(6, f"4K规格未达标", url, is_hktw)
                    return False
                return True

            max_jitter_normal = cfg.get('max_jitter_normal', 2.0)
            min_speed_normal = cfg.get('min_speed_normal', 180 * 1024)
            if max_jitter > max_jitter_normal or avg_speed < min_speed_normal:
                register_discard(6, f"稳定性未达标 (抖动:{max_jitter:.1f}s, 速度:{avg_speed/1024:.1f}KB/s)", url, is_hktw)
                return False
            return True
    except Exception as e:
        register_discard(6, f"测速阶段异常 ({type(e).__name__})", url, is_hktw)
        return False


def step7_8_ffmpeg_pipeline_audit(item, cfg, is_hktw):
    url = item["url"]
    category = item.get("category", "")
    FFMPEG_BIN = '/root/ffmpeg' if os.path.exists('/root/ffmpeg') else 'ffmpeg'
    timeout_video = cfg.get('timeout_video', 20.0)
    timeout_str = str(int(timeout_video * 1000000))

    cmd = [
        FFMPEG_BIN, '-y', '-rw_timeout', timeout_str,
        '-i', url, '-vframes', '30',
        '-vf', 'cropdetect=limit=32:round=2',
        '-f', 'null', '-'
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, timeout=timeout_video)

        if res.returncode != 0:
            if is_hktw and res.returncode == -11:
                print(f"   [港台放行] FFmpeg返回-11(SIGSEGV)，予以放行")
                return True
            register_discard(8, f"FFmpeg返回非0状态码 ({res.returncode})", url, is_hktw)
            # 拔除黑名单机制
            return False

        stderr_output = res.stderr
        video_line = next((line for line in stderr_output.split('\n')
                          if 'Stream #' in line and 'Video:' in line), None)
        if not video_line:
            register_discard(7, "无法解析Video轨道元数据", url, is_hktw)
            # 拔除黑名单机制
            return False

        res_match = re.search(r'(\d{3,4})x(\d{3,4})', video_line)
        width = int(res_match.group(1)) if res_match else 0
        height = int(res_match.group(2)) if res_match else 0

        if category == "4K超清":
            if height < 2160:
                register_discard(7, f"归类为4K But 分辨率仅{height}p（要求≥2160p）", url, is_hktw)
                # 拔除黑名单机制
                return False
        else:
            min_height = cfg.get('min_height', 720)
            if height < min_height:
                register_discard(7, f"分辨率过低 ({height}p < {min_height}p)", url, is_hktw)
                # 拔除黑名单机制
                return False

        speed_all = re.findall(r'speed=\s*([\d\.]+)x', stderr_output)
        allow_low_ratio = cfg.get('allow_low_ratio', False)
        if speed_all and not allow_low_ratio:
            try:
                speed_val = float(speed_all[-1])
                min_speed_ratio = cfg.get('min_speed_ratio', 0.8)
                if speed_val < min_speed_ratio:
                    register_discard(8, f"解码速率过低 ({speed_val}x < {min_speed_ratio}x)", url, is_hktw)
                    # 拔除黑名单机制
                    return False
            except:
                pass

        strict_frame_check = cfg.get('strict_frame_check', True)
        if strict_frame_check:
            if "frame=0" in stderr_output or "frame= " not in stderr_output:
                register_discard(8, "黑屏或无有效帧输出", url, is_hktw)
                # 拔除黑名单机制
                return False

        strict_zombie_check = cfg.get('strict_zombie_check', True)
        if strict_zombie_check:
            zombie_keywords = {
                "PPS id out of range": "NAL控制集错误",
                "Error parsing NAL unit": "NAL单元损坏",
                "Could not find ref with POC": "参考帧丢失",
                "corrupt decoded frame": "画面损坏"
            }
            for kw, desc in zombie_keywords.items():
                if kw in stderr_output:
                    register_discard(8, f"致命解码错误 ({desc})", url, is_hktw)
                    # 拔除黑名单机制
                    return False

        crop_lines = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr_output)
        if crop_lines and width > 0 and height > 0:
            crop_w, crop_h, _, _ = map(int, crop_lines[-1])
            max_border = cfg.get('max_black_border', 24)
            if (width - crop_w) > max_border or (height - crop_h) > max_border:
                register_discard(8, f"黑边过大 (> {max_border}像素)", url, is_hktw)
                # 拔除黑名单机制
                return False
        return True

    except subprocess.TimeoutExpired:
        register_discard(8, "FFmpeg执行超时", url, is_hktw)
        # 拔除黑名单机制
        return False
    except Exception as e:
        register_discard(8, f"FFmpeg执行异常 ({type(e).__name__})", url, is_hktw)
        # 拔除黑名单机制
        return False


def step9_generate_all_and_upload(domestic_list, hktw_list):
    print("[Step 9] 正在生成合并 live.m3u 并唤醒同步脚本...")

    def get_cctv_key(n):
        if "5+" in n:
            return 5.5
        m = re.search(r'CCTV-(\d+)', n)
        return int(m.group(1)) if m else 100

    def get_pinyin_key(n):
        p_map = {
            "安":"A","北":"B","重":"C","东":"D","广":"G","甘":"G","贵":"G",
            "湖":"H","河":"H","黑":"H","海":"H","江":"J","吉":"J","金":"J",
            "卡":"K","辽":"L","宁":"N","青":"Q","山":"S","深":"S","四":"S",
            "三":"S","天":"T","厦":"X","新":"X","西":"X","云":"Y","浙":"Z"
        }
        return f"{p_map.get(n[0], 'Z')}_{n}"

    domestic_grouped = defaultdict(lambda: defaultdict(list))
    for item in domestic_list:
        domestic_grouped[item["category"]][item["name"]].append(item["url"])

    hktw_grouped = defaultdict(list)
    for item in hktw_list:
        hktw_grouped[item["name"]].append(item["url"])

    custom_grouped = defaultdict(lambda: defaultdict(list))
    for ch in CUSTOM_CHANNELS:
        cat = ch.get("category", "自定义频道")
        name = ch.get("name", "")
        url = ch.get("url", "")
        if name and url:
            custom_grouped[cat][name].append(url)

    m3u_lines = ["#EXTM3U", f"# Update: {time.strftime('%Y-%m-%d %H:%M:%S')}"]

    # 1. 央视频道
    cat = "央视频道"
    channels = list(domestic_grouped[cat].keys())
    if channels:
        channels.sort(key=get_cctv_key)
        m3u_lines.append(f"\n# --- {cat} ---")
        for name in channels:
            urls = list(dict.fromkeys(domestic_grouped[cat][name]))
            migu = [u for u in urls if "miguvideo.com" in u or "cmvideo.cn" in u]
            others = [u for u in urls if u not in migu]
            for url in (migu + others):
                m3u_lines.append(f'#EXTINF:-1 group-title="{cat}",{name}')
                m3u_lines.append(url)

    # 2. 卫视频道
    cat = "卫视频道"
    channels = list(domestic_grouped[cat].keys())
    if channels:
        channels.sort(key=get_pinyin_key)
        m3u_lines.append(f"\n# --- {cat} ---")
        for name in channels:
            urls = list(dict.fromkeys(domestic_grouped[cat][name]))
            migu = [u for u in urls if "miguvideo.com" in u or "cmvideo.cn" in u]
            others = [u for u in urls if u not in migu]
            for url in (migu + others):
                m3u_lines.append(f'#EXTINF:-1 group-title="{cat}",{name}')
                m3u_lines.append(url)

    # 3. 港台频道
    if hktw_grouped:
        m3u_lines.append("\n# --- 港台频道 ---")
        for name in sorted(hktw_grouped.keys()):
            urls = list(dict.fromkeys(hktw_grouped[name]))
            for url in urls:
                m3u_lines.append(f'#EXTINF:-1 group-title="港台频道",{name}')
                m3u_lines.append(url)

    # 4. 自定义频道
    if custom_grouped:
        m3u_lines.append("\n# --- 自定义频道 ---")
        for cat_name in sorted(custom_grouped.keys()):
            for name in sorted(custom_grouped[cat_name].keys()):
                urls = list(dict.fromkeys(custom_grouped[cat_name][name]))
                for url in urls:
                    m3u_lines.append(f'#EXTINF:-1 group-title="{cat_name}",{name}')
                    m3u_lines.append(url)

    # 5. 4K超清
    cat = "4K超清"
    channels = list(domestic_grouped[cat].keys())
    if channels:
        channels.sort()
        m3u_lines.append(f"\n# --- {cat} ---")
        for name in channels:
            urls = list(dict.fromkeys(domestic_grouped[cat][name]))
            migu = [u for u in urls if "miguvideo.com" in u or "cmvideo.cn" in u]
            others = [u for u in urls if u not in migu]
            for url in (migu + others):
                m3u_lines.append(f'#EXTINF:-1 group-title="{cat}",{name}')
                m3u_lines.append(url)

    with open("./live.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    print("   -> 合并包已保存至当前目录下的 live.m3u")

    upload_script = "/root/upload.sh"
    if os.path.exists(upload_script):
        os.chmod(upload_script, 0o755)
        subprocess.run([upload_script])
        print("   -> 外部 upload.sh 脚本同步唤醒完成。")


# ==================== 主程序 ====================
def main():
    lives = step1_fetch_all_configs(CONFIG_SOURCES)
    if not lives:
        print("❌ 所有的订阅配置源抓取解析均失败，请检查网络或源有效性。")
        return

    survived_links = step2_parse_and_evict_dead_links(lives)
    if not survived_links:
        print("❌ 没有存活的链接，程序退出。")
        return

    domestic_raw, hktw_raw = step3_geo_ip_classify(survived_links)
    domestic_cleaned = step4_process_domestic_names(domestic_raw)
    hktw_cleaned = step5_process_hktw_names(hktw_raw)

    final_domestic_list = []
    final_hktw_list = []

    def run_quality_pipeline(item, is_hktw):
        url = item["url"]
        cfg = HKTW_CONFIG if is_hktw else MAINLAND_CONFIG
        print(f"【DEBUG】频道: {item.get('name')} | is_hktw={is_hktw} | "
              f"min_speed_normal={cfg.get('min_speed_normal', 0)/1024:.1f}KB/s")
        if not step6_stability_check(url, cfg, is_hktw):
            return None
        if not step7_8_ffmpeg_pipeline_audit(item, cfg, is_hktw):
            return None
        return item

    print(f"\n⚡ 进入并发质量流水线段 (线程数: {MAX_WORKERS})...")

    if domestic_cleaned:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as dom_executor:
            futures = {dom_executor.submit(run_quality_pipeline, item, False): item for item in domestic_cleaned}
            for f in as_completed(futures):
                res = f.result()
                if res:
                    final_domestic_list.append(res)

    if hktw_cleaned:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as hk_executor:
            futures = {hk_executor.submit(run_quality_pipeline, item, True): item for item in hktw_cleaned}
            for f in as_completed(futures):
                res = f.result()
                if res:
                    final_hktw_list.append(res)

    print(f"📊 检测结束：国内组 {len(final_domestic_list)} 条，港台组 {len(final_hktw_list)} 条。")

    step9_generate_all_and_upload(final_domestic_list, final_hktw_list)

    print("\n📝 正在导出 discard_report.txt ...")
    sorted_steps_dom = sorted(list(discard_registry_domestic.keys()))
    with open("./discard_report.txt", "w", encoding="utf-8") as rf:
        for step_header in sorted_steps_dom:
            rf.write(f"{step_header}\n")
            for url in discard_registry_domestic[step_header]:
                rf.write(f"{url}\n")
            rf.write("\n")

    merged_bl = flush_auto_blacklist()
    print(f"\n📚 自动学习黑名单: {len(merged_bl)} 条URL")

    print("🎉 审计完成。")


if __name__ == "__main__":
    main()