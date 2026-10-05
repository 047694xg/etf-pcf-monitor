"""
================================================================================
美股跨境ETF(纳指/标普500/美国50) 盘前官方PCF申赎限额监控引擎
- 定时标准: 每天早晨 08:05 准时执行并推送
- 深市标的 (159xxx): 直连深交所官方公开 PCF XML (智能探测最新可用与早间就绪轮询)
- 沪市标的 (51xxxx): 直连上交所官方公开 PCF XML (最新托管文件直接提取)
- 核心指标: 申购上限、单户上限、CU、最小申购赎回单位资产净值(NAVperCU)
- 微信通知: 永久纯文本 (msgtype: text)，无任何 Markdown 渲染，等宽对齐排版
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

# 监控标的池：全市场主流美股跨境 ETF (纳指100 / 标普500 / 美国50)
MONITOR_POOL = [
    # --- 深市跨境标的 ---
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

    # --- 沪市跨境标的 ---
    {"code": "513100", "name": "国泰纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513300", "name": "华夏纳斯达克", "market": "SH", "category": "纳指"},
    {"code": "513500", "name": "博时标普500",  "market": "SH", "category": "标普"},
    {"code": "513390", "name": "博时纳指100",  "market": "SH", "category": "纳指"},
    {"code": "513650", "name": "南方标普500",  "market": "SH", "category": "标普"},
    {"code": "513870", "name": "富国纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513850", "name": "易方达美国50", "market": "SH", "category": "美国50"},
    {"code": "513110", "name": "华泰柏瑞纳指", "market": "SH", "category": "纳指"},
    {"code": "513290", "name": "汇添富纳指生", "market": "SH", "category": "纳指"},
]

def str_display_width(s: str) -> int:
    """计算字符串在等宽终端/文本中的显示宽度(中文字符计为2)"""
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            w += 2
        else:
            w += 1
    return w

def pad_cjk(s: str, target_width: int) -> str:
    """根据东亚文字宽度对齐字符串"""
    current_w = str_display_width(s)
    if current_w >= target_width:
        return s
    return s + ' ' * (target_width - current_w)

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
    若在 08:00~08:15 之间当天文件未就绪，允许最多等待 60 秒轮询重试。
    若当天为休市/节假日，向前自动回溯最近的有效交易日。
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
    """深交所官方静态公开 PCF XML 解析"""
    url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{date_str}.xml"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=SZ_HEADERS, timeout=10)
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
                net_limit = float(g('NetCreationLimit', '0')) / 10000.0
                cum_limit = float(g('CreationLimit', '0')) / 10000.0
                user_net_limit = float(g('NetCreationLimitPerUser', '0')) / 10000.0
                creation = g('Creation', 'N')

                daily_quota = net_limit if net_limit > 0 else (cum_limit if cum_limit > 0 else 0.0)
                return {
                    "success": True,
                    "status": "开放" if creation == 'Y' else "暂停",
                    "quota": daily_quota,
                    "user_quota": user_net_limit,
                    "cu": cu,
                    "cu_nav": cu_nav,
                    "source": "深市"
                }
        except Exception as e:
            if attempt == 1:
                print(f"[WARN] 深交所 {code} 解析异常: {repr(e)}")
            time.sleep(0.5)
    return {"success": False, "status": "待查", "quota": 0.0, "user_quota": 0.0, "cu": 0.0, "cu_nav": 0.0, "source": "深市"}

def fetch_sse_pcf(code: str) -> dict:
    """上交所官方静态公开 PCF XML 直连解析"""
    url = f"https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do?fundCode={code}"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=SH_HEADERS, timeout=10)
            if r.status_code == 200 and b'SSEPortfolioCompositionFile' in r.content:
                root = ET.fromstring(r.content)
                d = {child.tag: child.text.strip() if child.text else '' for child in root if child.tag != 'ComponentList'}
                tday = d.get('TradingDay', '')
                cu = float(d.get('CreationRedemptionUnit', '0')) / 10000.0
                cu_nav = float(d.get('NAVperCU', '0')) / 10000.0  # 万元
                
                c_limit = float(d.get('CreationLimit') or d.get('NetCreationLimit') or 0.0) / 10000.0
                u_limit = float(d.get('CreationLimitPerAcct') or d.get('NetCreationLimitPerAcct') or 0.0) / 10000.0
                switch = d.get('CreationRedemptionSwitch', '1')
                st = "开放" if switch == '1' else "暂停"

                return {
                    "success": True,
                    "status": st,
                    "quota": c_limit,
                    "user_quota": u_limit,
                    "cu": cu,
                    "cu_nav": cu_nav,
                    "trade_date": tday,
                    "source": "沪市"
                }
        except Exception as e:
            if attempt == 1:
                print(f"[WARN] 上交所 {code} 解析异常: {repr(e)}")
            time.sleep(0.5)
    return {"success": False, "status": "待查", "quota": 0.0, "user_quota": 0.0, "cu": 0.0, "cu_nav": 0.0, "source": "沪市"}

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

    # 并发抓取加速响应
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda it: fetch_single_etf(it, sz_valid_date), MONITOR_POOL))

    # 按照当日上限 (quota) 由高到低降序排序；若上限相同则按 CU资产净值 降序
    results.sort(key=lambda x: (x.get('quota', 0.0), x.get('cu_nav', 0.0)), reverse=True)

    # 判断是否为休市留存
    if sz_valid_date != today_str:
        date_badge = f"{sz_valid_date}(休市留存)"
    else:
        date_badge = sz_valid_date

    lines = []
    lines.append("【08:05 盘前】美股跨境ETF申购限额官方监控 (按上限降序)")
    lines.append(f"基准日: {date_badge} | 模式: 沪深证券交易所官方直连")
    lines.append("-" * 60)
    lines.append("代码    简称          状态   当日上限   单户    CU   CU净值(万)  市场")
    lines.append("-" * 60)

    for it in results:
        code = it['code']
        name = it['name']
        st = it.get('status', '开放')
        
        q_val = it.get('quota', 0.0)
        u_val = it.get('user_quota', 0.0)
        cu_val = it.get('cu', 0.0)
        cu_nav_val = it.get('cu_nav', 0.0)
        src = it.get('source', '深市')

        if it.get('success'):
            quota_str = f"{q_val:>6.0f}万" if q_val > 0 else "  不限  "
            user_str = f"{u_val:>4.0f}万" if u_val > 0 else " 不限 "
            cu_str = f"{cu_val:>4.0f}万" if cu_val > 0 else "   -  "
            cu_nav_str = f"{cu_nav_val:>7.2f}万" if cu_nav_val > 0 else "    -   "
        else:
            quota_str = " 未披露 "
            user_str = "  -   "
            cu_str = "  -   "
            cu_nav_str = "    -   "

        name_col = pad_cjk(name, 12)
        lines.append(f"{code}  {name_col}  {st}  {quota_str:>7}  {user_str:>5}  {cu_str:>5}  {cu_nav_str:>9}  {src}")

    lines.append("-" * 60)
    lines.append("说明:")
    lines.append("1. 当日上限为基金公司事前申购总配额(万份)，高溢价时9:15竞价秒光;")
    lines.append("2. 单户限额为单一投资者账户当日申购封顶，CU为最小申赎单元(万份);")
    lines.append("3. CU净值为最小申购赎回单位资产净值(万元)，即申购1个CU所需资金;")
    lines.append("   (例如: 159509最小申赎单位资产净值为 1925734.54元 = 192.57万元);")
    lines.append("4. 数据源为沪深交易所盘前官方公开PCF XML清单，时效最高。")
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
