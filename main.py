import requests
import base64
import json
import re
import time
import sys
import subprocess
import socket
import os
from urllib.parse import urlparse, urljoin
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

print("=== TXT + M3U 终极版 (含地理位置过滤 + 画质几何与像素黑边审计) ===")

# ==================== 🛠️ 配置区 ====================
CATEGORIES = ["4K超清", "央视频道", "卫视频道", "港台频道"]

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

HK_TW_BRANDS = [
    "凤凰", "TVB", "翡翠台", "明珠台", "东森", "中天", "纬来", "三立", "八大", "年代", "非凡", 
    "华视", "台视", "民视", "公视", "中视", "TVBS", "靖天", "靖洋", "寰宇", "美亚", "影迷数位", "AMC", "香港卫视"
]

MAX_WORKERS = 20    # 保持 20 并发进行硬核像素审计

PLAYER_HEADERS = {
    'User-Agent': 'VLC/3.0.16 LibVLC/3.0.16',
    'Accept': '*/*',
    'Connection': 'close'
}
# ====================================================

def heal_mojibake(text):
    if not text: return ""
    mojibake_features = ['闋', '槌', '嚢', '涓', '鏂', '闆', '褰', '璺', '缈', '繝', '鐛', '嗃', '鑿']
    if any(f in text for f in mojibake_features):
        try:
            recovered = text.encode('gbk', errors='ignore').decode('utf-8', errors='ignore')
            if recovered and not any(f in recovered for f in mojibake_features):
                return recovered
        except:
            pass
    return text

def classify_channel(name):
    name_lower = name.lower().replace(" ", "")
    if len(name_lower) > 25: return None
    if "测试" in name_lower or "更新" in name_lower or "公告" in name_lower: return None
    
    if any(k.lower() in name_lower for k in HK_TW_BRANDS) or any(loc in name_lower for loc in ["香港", "台湾", "澳门"]):
        return "港台频道"
    if "4k" in name_lower or "8k" in name_lower or "uhd" in name_lower: 
        return "4K超清"
    if any(re.search(p, name_lower) for p in [r'cctv-?([1-9]|1[0-7])', r'中央([1-9]|1[0-7])[套频]', r'央视([1-9]|1[0-7])[套频]', r'cctv([1-9]|1[0-7])', r'cctv-?5\+']): 
        return "央视频道"
    for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
        if std_wei.lower() in name_lower:
            return "卫视频道"
    return None

def clean_and_standardize(raw_name, category):
    if not raw_name: return ""
    name = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}|（.*?）', '', raw_name)  
    name = re.sub(r'[_#\-\s\t｜|]', '', name).upper()  
    name = name.replace("雙語", "").replace("双语", "").replace("高清", "").replace("FHD", "").replace("HD", "")
    name = name.replace("緯來", "纬来").replace("東森", "东森").replace("中天", "中天").replace("鳳凰", "凤凰").replace("臺", "台")

    if category == "4K超清":
        if "8K" in name: return "CCTV 8K 超高清" if "CCTV" in name else name
        if "CCTV" in name or "中央" in name:
            match = re.search(r'(?:CCTV|中央|央视)([1-9]\d*)', name)
            if match and match.group(1) in ["1", "13", "16"]:
                return f"CCTV-{match.group(1)} {STANDARD_CCTV.get(match.group(1), '')} 4K".strip()
            return "CCTV 4K 超高清"
        for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
            if std_wei.replace("卫视", "") in name: return f"{std_wei} 4K"
        return name
    if category == "央视频道":
        match = re.search(r'(?:CCTV|中央|央视|中央电视台)([1-9]\d*\+?|[1-9])', name)
        if match:
            num = match.group(1)
            if num == "5+": return "CCTV-5+ 体育赛事"
            if num in STANDARD_CCTV: return f"CCTV-{num} {STANDARD_CCTV[num]}"
        if "5+" in name: return "CCTV-5+ 体育赛事"
        return name
    if category == "卫视频道":
        for std_wei in PROVINCIAL_SATELLITE_CHANNELS:
            if std_wei.replace("卫视", "").replace("卡通", "").replace("少儿", "") in name:
                return std_wei
        return name
    if category == "港台频道":
        return name 
    return name

def parse_txt_or_m3u(content, base_url=""):
    channels = []
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    is_m3u_format = any(line.startswith("#EXTINF") for line in lines[:20])

    if is_m3u_format:
        for i in range(len(lines)):
            if lines[i].startswith("#EXTINF:"):
                try:
                    name = lines[i].split(",")[-1].strip()
                    name = heal_mojibake(name) 
                    if i + 1 < len(lines) and not lines[i+1].startswith("#"):
                        url = lines[i+1].strip()
                        if url.startswith("http"):
                            if not url.startswith(("http://", "https://")): 
                                url = urljoin(base_url, url)
                            
                            if "auth=testpub" in url.lower() or "live.ottiptv.cc" in url.lower():
                                continue
                                
                            channels.append({"name": name, "url": url})
                except: pass
    else:
        for line in lines:
            if "#genre#" in line: continue
            if "," in line and "http" in line:
                try:
                    parts = line.split(",", 1)
                    name = parts[0].strip()
                    name = heal_mojibake(name) 
                    url = parts[1].strip()
                    if url.startswith("http"):
                        if not url.startswith(("http://", "https://")): 
                            url = urljoin(base_url, url)
                            
                        if "auth=testpub" in url.lower() or "live.ottiptv.cc" in url.lower():
                            continue
                            
                        channels.append({"name": name, "url": url})
                except: pass
    return channels


# ================= ⚡ 【测试代码完全一字不改完整移入】 =================
def audit_video_geometry(url):
    print(f"\n🔍 开始对目标直播源进行深度视讯审计...")
    print(f"🔗 URL: {url}")
    print("=" * 60)
    
    FFMPEG_BIN = '/root/ffmpeg' if os.path.exists('/root/ffmpeg') else 'ffmpeg'
    if FFMPEG_BIN == '/root/ffmpeg':
        print("🚀 检测到已外挂【全功能版 FFmpeg】，正在启用 CPU 纯软件深度扫描...")
    else:
        print("⚠️ 未找到外挂版本，正在尝试使用系统自带 FFmpeg（可能因阉割组件导致失败）...")

    def run_ffmpeg_probe():
        cmd = [
            FFMPEG_BIN, '-y', 
            '-rw_timeout', '5000000', 
            '-i', url,
            '-vframes', '30',         
            '-vf', 'cropdetect=limit=24:round=2', 
            '-f', 'null', '-'
        ]
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12.0)

    res = run_ffmpeg_probe()
    stderr_output = res.stderr

    # ==================== STEP 1: 从日志中逆向解析元数据 ====================
    width, height = 0, 0
    dar = "未标明"
    video_line = None
    
    for line in stderr_output.split('\n'):
        if 'Stream #' in line and 'Video:' in line:
            video_line = line
            break
            
    if video_line:
        print(f"\n📊 [流媒体底层透视]: {video_line.strip()}")
        
        res_match = re.search(r'(\d{3,4})x(\d{3,4})', video_line)
        if res_match:
            width = int(res_match.group(1))
            height = int(res_match.group(2))
        
        dar_match = re.search(r'DAR (\d+:\d+)', video_line)
        if dar_match:
            dar = dar_match.group(1)
            
        print(f"📊 [元数据规整报告]")
        print(f"  • 解析分辨率: {width} x {height}")
        print(f"  • 显示宽高比 (DAR): {dar}")
        
        if "4:3" in dar:
            print("\n🚨 【审计拦截】: 拒绝此源！元数据明确标注为 4:3。")
            return False
    else:
        print(f"\n❌ [解析失败] 无法从此直播源握手或提取到视频轨。错误摘要:\n{stderr_output.strip()[:300]}")
        return False

    # ==================== STEP 2: 像素层级硬编码黑边审计 ====================
    crop_lines = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr_output)
    
    if crop_lines:
        last_crop = crop_lines[-1]
        crop_w, crop_h, crop_x, crop_y = map(int, last_crop)
        
        print(f"\n🎨 [像素动态扫描报告]")
        print(f"  • 实际活动画面尺寸: {crop_w} x {crop_h}")
        print(f"  • 横向黑边偏移 (X轴): {crop_x} 像素")
        print(f"  • 纵向黑边偏移 (Y轴): {crop_y} 像素")
        
        if width > 0 and crop_x > (width * 0.06):
            actual_ratio = crop_w / crop_h
            print(f"\n🚨 【审计拦截】: 拒绝此源！检测到恶性【左右硬编码黑边/挤压变形】(Pillarbox)。")
            print(f"    ℹ️ 剥离黑边后，中间真实画面比例仅为 {actual_ratio:.2f}:1。")
            return False
            
        if height > 0 and crop_y > (height * 0.08):
            print(f"  ⚠️ 提示: 检测到【上下黑边】(Letterbox)。此为电影宽银幕模式，画面未变形，安全放行。")
        
        print("\n✅ 【审计通过】: 该直播源画面比例端正，无恶性左右黑边，判定为高品质源。")
        return True
    else:
        print("\n⚠️ [警告]: 未能从视频流中压榨出有效的像素切边数据，默认放行。")
        return True


def test_stream_alive_v2(url, category):
    try:
        with requests.get(url, headers=PLAYER_HEADERS, timeout=(4, 4), stream=True, allow_redirects=True) as r:
            if r.status_code not in [200, 206]: return url, False
            if 'text/html' in r.headers.get('Content-Type', '').lower(): return url, False
            
            chunk = next(r.iter_content(chunk_size=4096), None)
            if not chunk: return url, False
            
            is_m3u8 = False
            try:
                chunk_text = chunk.decode('utf-8', errors='ignore')
                if '#EXTM3U' in chunk_text or '#EXT-X-' in chunk_text: is_m3u8 = True
            except: pass
            
            start_time = time.time()
            total_bytes = len(chunk)
            
            for next_chunk in r.iter_content(chunk_size=8192):
                if not next_chunk: break
                total_bytes += len(next_chunk)
                if (time.time() - start_time) > 1.5: break
                    
            elapsed_time = time.time() - start_time
            if not is_m3u8 and elapsed_time > 0:
                if ((total_bytes * 8) / (elapsed_time * 1024)) < 500: return url, False
            
            if not audit_video_geometry(url): return url, False
            return url, True
    except Exception:
        return url, False


def get_cctv_sort_key(name):
    if "5+" in name: return 5.5
    match = re.search(r'CCTV-(\d+)', name)
    return int(match.group(1)) if match else 100

def get_pinyin_sort_key(name):
    pinyin_map = {"安":"A","北":"B","兵":"B","重":"C","东":"D","广":"G","甘":"G","贵":"G","湖":"H","河":"H","黑":"H","海":"H","江":"J","吉":"J","金":"J","嘉":"J","卡":"K","辽":"L","宁":"N","青":"Q","山":"S","深":"S","四":"S","三":"S","天":"T","厦":"X","新":"X","西":"X","流":"L","云":"Y","浙":"Z"}
    for k, v in pinyin_map.items():
        if name.startswith(k): return f"{v}_{name}"
    return f"Z_{name}"


def fetch_and_process():
    main_url = "https://ppsll.cc.cd/ppsll"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    try:
        print("正在抓取主配置链接...")
        resp = requests.get(main_url, headers=headers, timeout=15)
        resp.raise_for_status()

        encoded = resp.text.strip()
        if len(encoded) % 4 != 0: encoded += '=' * (4 - len(encoded) % 4)

        data = json.loads(base64.b64decode(encoded).decode('utf-8'))
        lives = data.get("lives", [])
        print(f"✅ 找到 {len(lives)} 个源列表，准备开始解析...\n")

        channel_pool = {cat: defaultdict(list) for cat in CATEGORIES}
        all_unique_urls = set()
        
        # 🆕 建立反向索引：记录每个 URL 属于哪些分类，方便后面精细化 IP 审计
        url_to_categories = defaultdict(set)

        for source in lives:
            src_name = source.get("name", "未知")
            src_url = source.get("url", "")
            if not src_url: continue
            
            content = None
            for retry in range(3):
                try:
                    r = requests.get(src_url, headers=headers, timeout=45)
                    r.raise_for_status()
                    content = r.content.decode('utf-8', errors='ignore')
                    break 
                except Exception as ex:
                    if retry < 2:
                        print(f"⚠️ 抓取 [{src_name}] 超时，正在进行第 {retry+1} 次重试...")
                        time.sleep(2)
                    else:
                        print(f"❌ 经历3次重试，放弃解析: {src_name:12} | 原因: {ex}")

            if not content: continue

            try:
                channels = parse_txt_or_m3u(content, src_url)
                valid_count = 0
                for ch in channels:
                    cat = classify_channel(ch["name"])
                    if cat:
                        std_name = clean_and_standardize(ch["name"], cat)
                        if std_name:
                            channel_pool[cat][std_name].append(ch["url"])
                            all_unique_urls.add(ch["url"])
                            url_to_categories[ch["url"]].add(cat)
                            valid_count += 1
                print(f"✔️ 成功解析: {src_name:12} | 抢救并清洗线路: {valid_count} 条")
            except Exception as e:
                print(f"❌ 处理数据流失败: {src_name:12} | 原因: {e}")


        # ================= 🌍 【IP 级地理位置审计拦截】 =================
        print(f"\n🌍 正在多线程并发解析 {len(all_unique_urls)} 个唯一域名的公网 IP 地址...")
        url_to_ip = {}
        unique_ips = set()
        
        def resolve_one(u):
            try:
                hostname = urlparse(u).hostname
                if hostname:
                    return u, socket.gethostbyname(hostname)
            except Exception:
                if hostname and ":" in hostname:
                    return u, hostname
            return u, None

        with ThreadPoolExecutor(max_workers=50) as executor:
            future_to_url = {executor.submit(resolve_one, u): u for u in all_unique_urls}
            for future in as_completed(future_to_url):
                u = future_to_url[future]
                try:
                    _, ip = future.result()
                    if ip:
                        url_to_ip[u] = ip
                        unique_ips.add(ip)
                except Exception: pass

        print(f"✅ 域名解析完成，合并得到 {len(unique_ips)} 个独立公网 IP。")
        print("📡 开始通过流水线批量检索地理位置，识别并卡死央视和卫视频道的境外源...")
        
        ip_to_country = {}
        unique_ips_list = list(unique_ips)
        batch_size = 100
        
        for i in range(0, len(unique_ips_list), batch_size):
            batch = unique_ips_list[i:i+batch_size]
            for retry in range(3):
                try:
                    response = requests.post(
                        "http://ip-api.com/batch?fields=status,countryCode,query",
                        json=batch,
                        timeout=15
                    )
                    if response.status_code == 200:
                        results = response.json()
                        for item in results:
                            if item.get("status") == "success":
                                ip_to_country[item.get("query")] = item.get("countryCode")
                        break
                    elif response.status_code == 429:
                        time.sleep(6) 
                except Exception:
                    time.sleep(2)
            time.sleep(1.2) 

        ALLOWED_COUNTRIES = ["CN"]
        filtered_unique_urls = set()
        discarded_by_geo = 0
        
        # 🆕 【核心改进】：港台频道直接豁免，仅对央视、卫视频道卡死 CN
        for url in all_unique_urls:
            cats = url_to_categories.get(url, set())
            
            # 如果此 URL 仅包含在港台频道中，直接过关，完全不检查 IP 地理位置
            if "港台频道" in cats and not (cats & {"央视频道", "卫视频道", "4K超清"}):
                filtered_unique_urls.add(url)
                continue
                
            # 否则（针对央视、卫视、4K等），继续执行严苛的本土 IP 审计
            ip = url_to_ip.get(url)
            if not ip: 
                # 拿不到 IP 意味着连域名都没解析出来，丢弃
                continue 
            
            country = ip_to_country.get(ip, "UNKNOWN")
            if country != "UNKNOWN" and country not in ALLOWED_COUNTRIES:
                discarded_by_geo += 1
                continue
            filtered_unique_urls.add(url)
            
        print(f"✂️ 地理审计完成：成功强力拦截并剔除了 {discarded_by_geo} 个国内卫视/央视的境外垃圾源！")
        print(f"📦 剩余 {len(filtered_unique_urls)} 个源（含免检港台源）进入最后的视讯精细体检。")


        # ================= 多线程并行测活与深度视讯特征审计 =================
        print(f"\n🚀 开始对幸存源进行视讯码率与画面几何特征深度审计...")
        
        url_with_cat_tasks = []
        for category in CATEGORIES:
            for std_name, urls in channel_pool[category].items():
                for url in urls:
                    if url in filtered_unique_urls: 
                        url_with_cat_tasks.append((url, category))
                        
        url_with_cat_tasks = list(dict.fromkeys(url_with_cat_tasks))

        valid_urls = set()
        completed = 0
        total_tasks = len(url_with_cat_tasks)
        start_test_time = time.time()

        # 20 线程稳健并发推进 FFmpeg 30帧硬核体检
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(test_stream_alive_v2, task[0], task[1]): task[0] for task in url_with_cat_tasks}
            
            for future in as_completed(future_to_url):
                completed += 1
                try:
                    url, is_alive = future.result()
                    if is_alive: valid_urls.add(url)
                    percent = int((completed / total_tasks) * 100)
                except Exception: pass

        cost_time = int(time.time() - start_test_time)
        print(f"\n\n视讯审计结束！耗时: {cost_time} 秒。正在写入最终高品质 M3U 文件...")
        
        final_m3u = ["#EXTM3U", f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        unique_channels_count = 0
        total_live_lines = 0
        
        for category in CATEGORIES:
            active_channels = [name for name, urls in channel_pool[category].items() if name]
            if not active_channels: continue
            
            if category == "央视频道": active_channels.sort(key=get_cctv_sort_key)
            elif category == "卫视频道": active_channels.sort(key=get_pinyin_sort_key)
            else: active_channels.sort()
                
            has_written_category = False
            
            for std_name in active_channels:
                urls = channel_pool[category][std_name]
                live_urls = [u for u in urls if u in valid_urls]
                live_urls = list(dict.fromkeys(live_urls)) 
                
                if not live_urls: continue
                if not has_written_category:
                    final_m3u.append(f"\n# --- {category} ---")
                    has_written_category = True
                
                unique_channels_count += 1
                
                migu_urls = [u for u in live_urls if "miguvideo.com" in u or "cmvideo.cn" in u]
                other_urls = [u for u in live_urls if u not in migu_urls]
                sorted_urls = migu_urls + other_urls
                
                for url in sorted_urls:
                    total_live_lines += 1
                    final_m3u.append(f'#EXTINF:-1 group-title="{category}",{std_name}')
                    final_m3u.append(url)

        with open("/www/live.m3u", 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_m3u))

        print(f"\n🎉 完美洗牌结束！")
        print(f"📊 审计统计: 最终保留了 {unique_channels_count} 个超清级国内及港台频道，共计 {total_live_lines} 条极速优质线路。")

    except Exception as e:
        print(f"\n❌ 发生严重全局错误: {e}")

if __name__ == "__main__":
    fetch_and_process()
