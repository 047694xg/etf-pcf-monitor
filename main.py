"""
================================================================================
美股跨境ETF(纳指/标普500/美国50/道琼斯/美股行业) 盘前官方PCF申赎限额与溢价率监控引擎
- 覆盖范围: 全市场 25 只全谱系美股跨境 QDII ETF (全网大满贯)
- 定时标准: 每天早晨 08:05 准时执行并推送 (周一至周五工作日运行，周六日静默)
- 沪市开关联动规范: CreationRedemptionSwitch in ('1', '2') 判定为开放；'3'(仅允许赎回)或'0'严格判定为暂停且申购上限归零
- 深市开关联动规范: Creation == 'Y' 判定为开放；'N' 严格判定为暂停且申购上限归零
- 微信通知: 永久纯文本 (msgtype: text)，无任何 Markdown 渲染，等宽对齐排版
- 排序规则: 开放申购优先且按有效申购上限由高到低降序；暂停申购标的自动沉底
================================================================================
"""
import os
import sys
import time
import datetime
import unicodedata
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_WEBHOOK = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=35698b2f-960f-4ce8-b7bb-a4ac60888d9d'
WECHAT_WEBHOOK = os.getenv('WECHAT_WEBHOOK') or DEFAULT_WEBHOOK

SZ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

SH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.sse.com.cn/'
}

# 监控标的池：全市场 25 只全谱系美股跨境 ETF (纳指100 / 标普500 / 美国50 / 道琼斯 / 美股行业)
MONITOR_POOL = [
    # --- 深市跨境标的 (14 只) ---
    {"code": "159509", "name": "景顺纳指科技", "market": "SZ", "category": "纳指"},
    {"code": "159501", "name": "嘉实纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159513", "name": "大成纳指100",  "market": "SZ", "category": "纳指"},
    {"code": "159632", "name": "华安纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159659", "name": "招商纳指100",  "market": "SZ", "category": "纳指"},
    {"code": "159660", "name": "汇添富纳指",   "market": "SZ", "category": "纳指"},
    {"code": "159696", "name": "易方达纳指",   "market": "SZ", "category": "纳指"},
    {"code": "159941", "name": "广发纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159655", "name": "华夏标普500",  "market": "SZ", "category": "标普"},
    {"code": "159612", "name": "国泰标普500",  "market": "SZ", "category": "标普"},
    {"code": "159577", "name": "汇添富美国50", "market": "SZ", "category": "美国50"},
    {"code": "159502", "name": "标普生物科技", "market": "SZ", "category": "生物科技"},
    {"code": "159529", "name": "标普消费ETF",  "market": "SZ", "category": "标普消费"},
    {"code": "159518", "name": "嘉实标普油气", "market": "SZ", "category": "标普油气"},

    # --- 沪市跨境标的 (11 只) ---
    {"code": "513100", "name": "国泰纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513300", "name": "华夏纳斯达克", "market": "SH", "category": "纳指"},
    {"code": "513500", "name": "博时标普500",  "market": "SH", "category": "标普"},
    {"code": "513390", "name": "博时纳指100",  "market": "SH", "category": "纳指"},
    {"code": "513650", "name": "南方标普500",  "market": "SH", "category": "标普"},
    {"code": "513870", "name": "富国纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513850", "name": "易方达美国50", "market": "SH", "category": "美国50"},
    {"code": "513110", "name": "华泰柏瑞纳指", "market": "SH", "category": "纳指"},
    {"code": "513290", "name": "汇添富纳指生", "market": "SH", "category": "纳指"},
    {"code": "513400", "name": "道琼斯ETF",    "market": "SH", "category": "道琼斯"},
    {"code": "513350", "name": "富国标普油气", "market": "SH", "category": "标普油气"},
]

def str_display_width(s: str) -> int:
    """计算字符串在等宽终端/文本中的显示宽度(中文字符计为2)"""
    return sum(2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1 for ch in s)

def pad_cjk(s: str, target_width: int) -> str:
    """根据东亚文字宽度对齐字符串"""
    current_w = str_display_width(s)
    if current_w >= target_width:
        return s
    return s + ' ' * (target_width - current_w)

def fetch_all_close_prices(pool: list) -> dict:
    """
    轻量极速批量获取所有监控 ETF 的上一交易日收盘价 (腾讯行情直连)
    零外部大库依赖，毫秒级响应
    """
    symbols = [f"{it['market'].lower()}{it['code']}" for it in pool]
    url = f"http://qt.gtimg.cn/q={','.join(symbols)}"
    try:
        r = requests.get(url, timeout=5)
        price_map = {}
        for line in r.text.split(';'):
            line = line.strip()
            if not line:
                continue
            parts = line.split('~')
            if len(parts) > 4:
                code = parts[2]
                close_p = float(parts[3]) if parts[3] and float(parts[3]) > 0 else float(parts[4])
                price_map[code] = close_p
        return price_map
    except Exception as e:
        print(f"[WARN] 批量获取收盘价异常: {repr(e)}")
        return {}

def check_szse_file_exists(code: str, date_str: str) -> bool:
    url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{date_str}.xml"
    try:
        r = requests.head(url, headers=SZ_HEADERS, timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def probe_latest_szse_date(benchmark_code: str = "159509") -> str:
    """
    智能探查深交所最新有效 PCF 文件日期。
    """
    now = datetime.datetime.now()
    today_str = now.strftime("%Y%m%d")

    # 如果是交易日早晨 07:50~08:15 窗口期，先尝试轮询当天文件是否刚发布
    if now.weekday() < 5 and 7 <= now.hour <= 8:
        for retry in range(2):
            if check_szse_file_exists(benchmark_code, today_str):
                return today_str
            time.sleep(2)

    # 检查今天是否存在
    if check_szse_file_exists(benchmark_code, today_str):
        return today_str

    # 若今天未挂出或休市，向前回溯查找最近有效日
    for days_back in range(1, 12):
        check_dt = now - datetime.timedelta(days=days_back)
        d_str = check_dt.strftime("%Y%m%d")
        if check_szse_file_exists(benchmark_code, d_str):
            return d_str

    return today_str

def fetch_szse_pcf(code: str, date_str: str) -> dict:
    """深交所官方静态公开 PCF XML 解析 (严格联动申购开关)"""
    url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{date_str}.xml"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=SZ_HEADERS, timeout=8)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                ns = {'ns': 'http://ts.szse.cn/Fund'}
                def g(tag, d='0'):
                    el = root.find(f'ns:{tag}', ns)
                    if el is None:
                        el = root.find(tag)
                    return el.text.strip() if el is not None and el.text else d

                cu = float(g('CreationRedemptionUnit', '0')) / 10000.0
                cu_nav = float(g('NAVperCU', '0')) / 10000.0  # 万元
                nav = float(g('NAV', '0'))
                creation = g('Creation', 'N')

                # 严格限定申购权限：只有明确 Creation == 'Y' 才能申购
                is_creation_open = (creation == 'Y')
                if is_creation_open:
                    st = "开放"
                    net_limit = float(g('NetCreationLimit', '0')) / 10000.0
                    cum_limit = float(g('CreationLimit', '0')) / 10000.0
                    u_limit = float(g('NetCreationLimitPerUser', '0')) / 10000.0
                    daily_quota = net_limit if net_limit > 0 else (cum_limit if cum_limit > 0 else 0.0)
                else:
                    st = "暂停"
                    daily_quota = 0.0  # 暂停申购时，有效申购上限强制归零
                    u_limit = 0.0

                return {
                    "success": True,
                    "status": st,
                    "quota": daily_quota,
                    "user_quota": u_limit,
                    "cu": cu,
                    "cu_nav": cu_nav,
                    "nav": nav,
                    "source": "深市"
                }
        except Exception as e:
            if attempt == 1:
                print(f"[WARN] 深交所 {code} 解析异常: {repr(e)}")
            time.sleep(0.5)
    return {"success": False, "status": "待查", "quota": 0.0, "user_quota": 0.0, "cu": 0.0, "cu_nav": 0.0, "nav": 0.0, "source": "深市"}

def fetch_sse_pcf(code: str) -> dict:
    """上交所官方静态公开 PCF XML 直连解析 (严格按上交所规范联动申购开关)"""
    url = f"https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do?fundCode={code}"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=SH_HEADERS, timeout=8)
            if r.status_code == 200 and b'SSEPortfolioCompositionFile' in r.content:
                root = ET.fromstring(r.content)
                d = {child.tag: child.text.strip() if child.text else '' for child in root if child.tag != 'ComponentList'}
                tday = d.get('TradingDay', '')
                cu = float(d.get('CreationRedemptionUnit', '0')) / 10000.0
                cu_nav = float(d.get('NAVperCU', '0')) / 10000.0  # 万元
                nav = float(d.get('NAV') or 0.0)
                
                # 上交所官方枚举: '1'=申赎皆允许; '2'=仅允许申购; '3'=仅允许赎回(禁申); '0'=不允许申赎
                switch = str(d.get('CreationRedemptionSwitch', '0')).strip()
                is_creation_open = switch in ('1', '2')

                if is_creation_open:
                    st = "开放"
                    c_limit = float(d.get('CreationLimit') or d.get('NetCreationLimit') or 0.0) / 10000.0
                    u_limit = float(d.get('CreationLimitPerAcct') or d.get('NetCreationLimitPerAcct') or 0.0) / 10000.0
                else:
                    st = "暂停"
                    c_limit = 0.0  # 暂停申购时，有效申购上限强制归零
                    u_limit = 0.0

                return {
                    "success": True,
                    "status": st,
                    "quota": c_limit,
                    "user_quota": u_limit,
                    "cu": cu,
                    "cu_nav": cu_nav,
                    "nav": nav,
                    "trade_date": tday,
                    "source": "沪市"
                }
        except Exception as e:
            if attempt == 1:
                print(f"[WARN] 上交所 {code} 解析异常: {repr(e)}")
            time.sleep(0.5)
    return {"success": False, "status": "待查", "quota": 0.0, "user_quota": 0.0, "cu": 0.0, "cu_nav": 0.0, "nav": 0.0, "source": "沪市"}

def fetch_single_etf(item: dict, sz_target_date: str) -> dict:
    code = item['code']
    market = item['market']
    if market == 'SZ':
        res = fetch_szse_pcf(code, sz_target_date)
    else:
        res = fetch_sse_pcf(code)
    return {**item, **res}

def build_pure_text_report() -> str:
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    sz_valid_date = probe_latest_szse_date("159509")

    # 1. 批量获取上一交易日收盘价
    close_prices = fetch_all_close_prices(MONITOR_POOL)

    # 2. 并发抓取官方 PCF XML (25只全谱系标的)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda it: fetch_single_etf(it, sz_valid_date), MONITOR_POOL))

    # 3. 计算收盘溢价率: (收盘价 - 基金份额净值NAV) / NAV * 100%
    for it in results:
        code = it['code']
        close_p = close_prices.get(code, 0.0)
        nav = it.get('nav', 0.0)
        it['close_price'] = close_p
        if nav > 0 and close_p > 0:
            it['premium_rate'] = ((close_p - nav) / nav) * 100.0
        else:
            it['premium_rate'] = None

    # 4. 排序规则: 开放申购优先，在开放标的中按有效申购上限(quota)降序；暂停标的自动沉底
    results.sort(key=lambda x: (1 if x.get('status') == '开放' else 0, x.get('quota', 0.0), x.get('cu_nav', 0.0)), reverse=True)

    # 判断是否为休市留存
    if sz_valid_date != today_str:
        date_badge = f"{sz_valid_date}(休市留存)"
    else:
        date_badge = sz_valid_date

    lines = []
    lines.append("【08:05 盘前】美股跨境ETF申购限额官方监控 (全市场25只)")
    lines.append(f"基准日: {date_badge} | 模式: 沪深证券交易所官方直连")
    lines.append("-" * 76)
    headers = ['代码  ', '简称' + ' ' * 10, '状态', '当日上限', '  单户', '    CU', 'CU净值(万)', '  溢价率']
    lines.append("  ".join(headers))
    lines.append("-" * 76)

    for it in results:
        code = it['code']
        name = it['name']
        st = it.get('status', '开放')
        
        q_val = it.get('quota', 0.0)
        u_val = it.get('user_quota', 0.0)
        cu_val = it.get('cu', 0.0)
        cu_nav_val = it.get('cu_nav', 0.0)
        prem_val = it.get('premium_rate')

        if it.get('success'):
            if st == "开放":
                quota_str = f"{q_val:>6.0f}万" if q_val > 0 else "  不限  "
                user_str = f"{u_val:>4.0f}万" if u_val > 0 else "  不限"
            else:
                quota_str = "  暂停  "
                user_str = "   -  "
            cu_str = f"{cu_val:>4.0f}万" if cu_val > 0 else "   -  "
            cu_nav_str = f"{cu_nav_val:>8.2f}万" if cu_nav_val > 0 else "    -     "
        else:
            quota_str = " 未披露 "
            user_str = "  -   "
            cu_str = "   -  "
            cu_nav_str = "    -     "

        if prem_val is not None:
            prem_str = f"{prem_val:>+7.1f}%"
        else:
            prem_str = "   -    "

        name_col = pad_cjk(name, 14)
        lines.append(f"{code}  {name_col}  {st}  {quota_str}  {user_str}  {cu_str}  {cu_nav_str}  {prem_str}")

    lines.append("-" * 76)
    lines.append("说明:")
    lines.append("1. 当日上限严格限定为有效申购额度(万份)，开关关闭(禁申/暂停)时额度归零;")
    lines.append("2. 单户限额为单一投资者账户当日申购封顶，CU为最小申赎单元(万份);")
    lines.append("3. CU净值为最小申购赎回单位资产净值(万元)，即申购1个CU所需资金;")
    lines.append("4. 溢价率=(上交易日二级市场收盘价 - 官方PCF净值(NAV)) / NAV * 100%;")
    lines.append("5. 数据源为沪深交易所盘前官方公开PCF XML清单，时效最高。")
    return "\n".join(lines)

def send_wechat_text(content: str) -> dict:
    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    r = requests.post(WECHAT_WEBHOOK, json=payload, timeout=6)
    return r.json()

if __name__ == '__main__':
    msg = build_pure_text_report()
    print("=== 纯文本报表预览 ===")
    print(msg)
    res = send_wechat_text(msg)
    print("=== 微信推送结果 ===", res)
