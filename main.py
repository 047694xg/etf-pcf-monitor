"""
================================================================================
美股跨境ETF(纳指/标普500) 盘前官方PCF申赎限额监控引擎 (方案2专属解析器体系)
- 深市标的 (159xxx): 直连深交所官方静态公开 PCF XML (reportdocs.static.szse.cn)
- 沪市标的 (51xxxx): 配属国泰/华夏/博时/南方/易方达等基金公司专属解析器 (强日期校验)
- 微信通知: 永久纯文本 (msgtype: text)，无任何 Markdown 渲染，等宽对齐
================================================================================
"""
import requests
import xml.etree.ElementTree as ET
import datetime
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_WEBHOOK = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=35698b2f-960f-4ce8-b7bb-a4ac60888d9d'
WECHAT_WEBHOOK = os.getenv('WECHAT_WEBHOOK') or DEFAULT_WEBHOOK

HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}

# 监控标的池
MONITOR_POOL = [
    # --- 深市标的 (SZSE 官方直连) ---
    {"code": "159509", "name": "景顺纳指科技", "market": "SZ", "company": "景顺长城", "category": "纳指"},
    {"code": "159501", "name": "嘉实纳指ETF",  "market": "SZ", "company": "嘉实基金", "category": "纳指"},
    {"code": "159513", "name": "大成纳指100",  "market": "SZ", "company": "大成基金", "category": "纳指"},
    {"code": "159632", "name": "华安纳指ETF",  "market": "SZ", "company": "华安基金", "category": "纳指"},
    {"code": "159659", "name": "招商纳指100",  "market": "SZ", "company": "招商基金", "category": "纳指"},
    {"code": "159660", "name": "汇添富纳指",   "market": "SZ", "company": "汇添富",   "category": "纳指"},
    {"code": "159696", "name": "易方达纳指",   "market": "SZ", "company": "易方达",   "category": "纳指"},
    {"code": "159941", "name": "广发纳指ETF",  "market": "SZ", "company": "广发基金", "category": "纳指"},
    {"code": "159612", "name": "国泰标普500",  "market": "SZ", "company": "国泰基金", "category": "标普"},
    {"code": "159655", "name": "华夏标普500",  "market": "SZ", "company": "华夏基金", "category": "标普"},
    {"code": "159577", "name": "汇添富美国50", "market": "SZ", "company": "汇添富",   "category": "美国50"},
    # --- 沪市标的 (SSE 基金公司专属解析器) ---
    {"code": "513100", "name": "国泰纳指ETF",  "market": "SH", "company": "国泰基金", "category": "纳指"},
    {"code": "513300", "name": "华夏纳斯达克", "market": "SH", "company": "华夏基金", "category": "纳指"},
    {"code": "513500", "name": "博时标普500",  "market": "SH", "company": "博时基金", "category": "标普"},
    {"code": "513390", "name": "博时纳指100",  "market": "SH", "company": "博时基金", "category": "纳指"},
    {"code": "513650", "name": "南方标普500",  "market": "SH", "company": "南方基金", "category": "标普"},
    {"code": "513870", "name": "富国纳指ETF",  "market": "SH", "company": "富国基金", "category": "纳指"},
    {"code": "513850", "name": "易方达美国50", "market": "SH", "company": "易方达",   "category": "美国50"},
    {"code": "513110", "name": "华泰柏瑞纳指", "market": "SH", "company": "华泰柏瑞", "category": "纳指"},
    {"code": "513290", "name": "汇添富纳指生", "market": "SH", "company": "汇添富",   "category": "纳指"},
]

# ==============================================================================
# 1. 深交所官方静态公开 PCF XML 解析器
# ==============================================================================
def fetch_szse_pcf_official(code: str, date_str: str) -> dict:
    url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{date_str}.xml"
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            ns = {'ns': 'http://ts.szse.cn/Fund'}
            def g(tag, d='0'):
                el = root.find(f'ns:{tag}', ns)
                if el is None:
                    el = root.find(tag)
                return el.text.strip() if el is not None and el.text else d

            cu = float(g('CreationRedemptionUnit', '0')) / 10000.0
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
                "source": "深交所PCF"
            }
    except Exception:
        pass
    return {"success": False, "msg": "未披露"}

# ==============================================================================
# 2. 上交所主流品种专属基金公司解析器 (方案2)
# ==============================================================================
def parse_gtfund_513100(target_date: str) -> dict:
    """国泰基金 (513100) 专属解析器"""
    url = "https://www.gtfund.com/service/etf/pcfInfo"
    try:
        r = requests.get(url, params={"fundCode": "513100", "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('netCreationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "国泰官网"}
    except Exception:
        pass
    return {"success": False, "source": "国泰官网", "msg": "待官网刷新"}

def parse_chinaamc_513300(target_date: str) -> dict:
    """华夏基金 (513300) 专属解析器"""
    url = "https://fund.chinaamc.com/portal/etf/pcf_detail.json"
    try:
        r = requests.get(url, params={"fundCode": "513300", "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('creationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "华夏官网"}
    except Exception:
        pass
    return {"success": False, "source": "华夏官网", "msg": "待官网刷新"}

def parse_bosera_513500(target_date: str, code: str = "513500") -> dict:
    """博时基金 (513500 / 513390) 专属解析器"""
    url = "https://www.bosera.com/fund/etf/pcfInfo.json"
    try:
        r = requests.get(url, params={"fundCode": code, "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('netCreationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "博时官网"}
    except Exception:
        pass
    return {"success": False, "source": "博时官网", "msg": "待官网刷新"}

def parse_nffund_513650(target_date: str) -> dict:
    """南方基金 (513650) 专属解析器"""
    url = "https://www.nffund.com/service/etf/pcf.json"
    try:
        r = requests.get(url, params={"fundCode": "513650", "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('netCreationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "南方官网"}
    except Exception:
        pass
    return {"success": False, "source": "南方官网", "msg": "待官网刷新"}

def parse_efunds_513850(target_date: str) -> dict:
    """易方达基金 (513850) 专属解析器"""
    url = "https://www.efunds.com.cn/funds/etf/pcfInfo.json"
    try:
        r = requests.get(url, params={"fundCode": "513850", "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('creationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "易方达官网"}
    except Exception:
        pass
    return {"success": False, "source": "易方达官网", "msg": "待官网刷新"}

def parse_fullgoal_513870(target_date: str) -> dict:
    """富国基金 (513870) 专属解析器"""
    url = "https://www.fullgoal.com.cn/service/etf/pcfInfo.json"
    try:
        r = requests.get(url, params={"fundCode": "513870", "date": target_date}, headers=HTTP_HEADERS, timeout=4)
        if r.status_code == 200:
            d = r.json()
            if str(d.get('date', '')).replace('-', '') == target_date:
                quota = float(d.get('netCreationLimit', 0.0)) / 10000.0
                user_q = float(d.get('userLimit', 0.0)) / 10000.0
                cu = float(d.get('cu', 1000000.0)) / 10000.0
                return {"success": True, "quota": quota, "user_quota": user_q, "cu": cu, "status": "开放", "source": "富国官网"}
    except Exception:
        pass
    return {"success": False, "source": "富国官网", "msg": "待官网刷新"}

SSE_PARSER_ROUTER = {
    "513100": parse_gtfund_513100,
    "513300": parse_chinaamc_513300,
    "513500": lambda dt: parse_bosera_513500(dt, "513500"),
    "513390": lambda dt: parse_bosera_513500(dt, "513390"),
    "513650": parse_nffund_513650,
    "513870": parse_fullgoal_513870,
    "513850": parse_efunds_513850,
}

def dispatch_sse_pcf(code: str, target_date: str, company_name: str) -> dict:
    fn = SSE_PARSER_ROUTER.get(code)
    if fn:
        res = fn(target_date)
        if res.get("success"):
            return res
    # 默认返回带有基金公司信源的未刷新标识
    return {"success": False, "source": f"{company_name[:2]}官网", "msg": "待官网刷新"}

# ==============================================================================
# 3. 构造纯文本报表 (严禁 Markdown 渲染)
# ==============================================================================
def build_pure_text_report(trade_date: str = None) -> str:
    if not trade_date:
        today = datetime.date.today()
        trade_date = "20260930" if today.weekday() >= 5 else today.strftime("%Y%m%d")

    lines = []
    lines.append("【08:15 盘前】美股跨境ETF申购限额官方监控")
    lines.append(f"基准日: {trade_date} | 模式: 官方直连+基金公司专属解析器")
    lines.append("-" * 46)
    lines.append("代码   简称         状态   当日上限    单户    CU   信源")
    lines.append("-" * 46)

    for item in MONITOR_POOL:
        code = item['code']
        market = item['market']
        name = item['name']
        company = item['company']
        name_pad = name.ljust(6, '　') if len(name) < 6 else name[:6]

        if market == 'SZ':
            pcf = fetch_szse_pcf_official(code, trade_date)
            if pcf.get("success"):
                st = pcf['status']
                quota = f"{pcf['quota']:>6.0f}万" if pcf['quota'] > 0 else "  不限  "
                user_q = f"{pcf['user_quota']:>4.0f}万" if pcf['user_quota'] > 0 else " 不限 "
                cu = f"{pcf['cu']:>3.0f}万"
                src = "深交所PCF"
            else:
                st = "待查"
                quota = "  未披露 "
                user_q = "  -   "
                cu = "  -   "
                src = "深交所"
        else:
            # 沪市专属解析器
            pcf = dispatch_sse_pcf(code, trade_date, company)
            src = pcf.get("source", "基金官网")
            if pcf.get("success"):
                st = pcf.get("status", "开放")
                quota = f"{pcf['quota']:>6.0f}万" if pcf['quota'] > 0 else "  不限  "
                user_q = f"{pcf['user_quota']:>4.0f}万" if pcf['user_quota'] > 0 else " 不限 "
                cu = f"{pcf['cu']:>3.0f}万"
            else:
                st = "开放"
                quota = f"[{pcf.get('msg', '待刷新')}]"
                user_q = " 见公告"
                cu = " 见公告"

        lines.append(f"{code}  {name_pad} {st}  {quota}  {user_q}  {cu}  {src}")

    lines.append("-" * 46)
    lines.append("说明:")
    lines.append("1. 当日上限为基金公司事前申购总配额(万份)，高溢价下9:15集合竞价秒光;")
    lines.append("2. 深市直连深交所官方PCF XML; 沪市由各公募基金公司专属解析器提取;")
    lines.append("3. 若基金公司08:15前尚未刷新官网CMS，将自动标明[待官网刷新]，防范旧数据误导。")
    return "\n".join(lines)

def send_wechat_text(content: str):
    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    r = requests.post(WECHAT_WEBHOOK, json=payload, timeout=5)
    return r.json()

if __name__ == '__main__':
    trade_date = "20260930" if datetime.date.today().weekday() >= 5 else datetime.date.today().strftime('%Y%m%d')
    msg = build_pure_text_report(trade_date)
    print("=== 纯文本报表预览 ===")
    print(msg)
    res = send_wechat_text(msg)
    print("=== 微信推送结果 ===", res)
