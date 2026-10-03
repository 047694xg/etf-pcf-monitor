"""
美股跨境ETF(纳指/标普500) 交易所官方PCF申赎限额盘前监控
纯文本推送 (无Markdown渲染)
"""
import requests
import xml.etree.ElementTree as ET
import datetime
import os
import sys

# 企业微信 Webhook (优先从环境变量读取，默认保底)
DEFAULT_WEBHOOK = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=35698b2f-960f-4ce8-b7bb-a4ac60888d9d'
WECHAT_WEBHOOK = os.getenv('WECHAT_WEBHOOK') or DEFAULT_WEBHOOK

# 核心纳指与标普500跨境ETF监控池
MONITOR_POOL = [
    # --- 深市标的 (SZSE - 交易所官方直连) ---
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
    # --- 沪市标的 (SSE) ---
    {"code": "513100", "name": "国泰纳指ETF",  "market": "SH", "company": "国泰基金", "category": "纳指"},
    {"code": "513110", "name": "华泰柏瑞纳指", "market": "SH", "company": "华泰柏瑞", "category": "纳指"},
    {"code": "513300", "name": "华夏纳斯达克", "market": "SH", "company": "华夏基金", "category": "纳指"},
    {"code": "513390", "name": "博时纳指100",  "market": "SH", "company": "博时基金", "category": "纳指"},
    {"code": "513870", "name": "富国纳指ETF",  "market": "SH", "company": "富国基金", "category": "纳指"},
    {"code": "513290", "name": "汇添富纳指生", "market": "SH", "company": "汇添富",   "category": "纳指"},
    {"code": "513500", "name": "博时标普500",  "market": "SH", "company": "博时基金", "category": "标普"},
    {"code": "513650", "name": "南方标普500",  "market": "SH", "company": "南方基金", "category": "标普"},
    {"code": "513850", "name": "易方达美国50", "market": "SH", "company": "易方达",   "category": "美国50"},
]

def fetch_szse_pcf_official(code: str, date_str: str) -> dict:
    """
    深交所官方静态公开 PCF XML 直连解析 (盘前 07:30~08:15 发布)
    """
    url = f"https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{date_str}.xml"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=5)
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
                "status": "开放" if creation == 'Y' else "暂停",
                "daily_quota": daily_quota,
                "user_quota": user_net_limit,
                "cu": cu,
                "nav": float(g('NAV', '0.0')),
            }
    except Exception:
        pass
    return None

def fetch_jisilu_snapshot() -> dict:
    """
    备选快照：用于沪市标的与盘前清算新增校验
    """
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.jisilu.cn/data/qdii/',
        'X-Requested-With': 'XMLHttpRequest'
    }
    url = "https://www.jisilu.cn/data/qdii/qdii_list/E"
    res = {}
    try:
        r = requests.get(url, params={"rp": "50"}, headers=headers, timeout=5)
        if r.status_code == 200:
            for row in r.json().get('rows', []):
                c = row.get('cell', {})
                fid = c.get('fund_id')
                if fid:
                    res[fid] = {
                        "amount_incr": float(c.get('amount_incr') or 0.0),
                        "status": c.get('apply_status', '待查')
                    }
    except Exception:
        pass
    return res

def build_pure_text_message(trade_date: str = None) -> str:
    """
    生成纯文本通知 (无Markdown渲染，手机端不折行、不形变)
    """
    if not trade_date:
        trade_date = datetime.date.today().strftime('%Y%m%d')

    snapshot = fetch_jisilu_snapshot()
    lines = []
    lines.append(f"【08:15 盘前】美股跨境ETF申购限额官方监控")
    lines.append(f"基准日: {trade_date} | 模式: 交易所直连")
    lines.append("-" * 38)
    lines.append("代码  简称          状态  当日上限   单户  CU")
    lines.append("-" * 38)

    for item in MONITOR_POOL:
        code = item['code']
        market = item['market']
        name = item['name']
        
        # 补齐简称宽度
        name_pad = name.ljust(6, '　') if len(name) < 6 else name[:6]

        if market == 'SZ':
            pcf = fetch_szse_pcf_official(code, trade_date)
            if pcf:
                st = pcf['status']
                quota = f"{pcf['daily_quota']:>6.0f}万" if pcf['daily_quota'] > 0 else "  不限  "
                user_q = f"{pcf['user_quota']:>4.0f}万" if pcf['user_quota'] > 0 else " 不限 "
                cu = f"{pcf['cu']:>3.0f}万"
            else:
                st = "待查"
                quota = "  未披露 "
                user_q = "  -  "
                cu = "  -  "
        else:
            # 沪市标的 (结合盘前新增)
            snap = snapshot.get(code, {})
            st = snap.get('status', '待查')
            incr = snap.get('amount_incr', 0.0)
            quota = f"{incr:>6.0f}万" if incr > 0 else "0/见公告"
            user_q = " 见公告"
            cu = " 见公告"

        lines.append(f"{code} {name_pad} {st} {quota} {user_q} {cu}")

    lines.append("-" * 38)
    lines.append("注: 当日上限为全市场允许累计申购总量(万份)。高溢价下9:15集合竞价秒光。")
    return "\n".join(lines)

def send_wechat_text(content: str):
    """
    纯文本格式推送至企业微信 (msgtype: text)
    """
    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    r = requests.post(WECHAT_WEBHOOK, json=payload, timeout=5)
    return r.json()

if __name__ == '__main__':
    # 自动获取当日
    today_str = datetime.date.today().strftime('%Y%m%d')
    # 周末或节假日取最近交易日做容错
    if datetime.date.today().weekday() >= 5:
        # 演示用最近交易日
        today_str = "20260930"
        
    msg = build_pure_text_message(today_str)
    print("=== 纯文本预览 ===")
    print(msg)
    print("=== 推送结果 ===")
    res = send_wechat_text(msg)
    print(res)
