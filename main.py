"""
美股跨境ETF(纳指/标普500) 沪深交易所官方直连盘前监控
纯文本推送 (无Markdown渲染，零第三方截断)
- 深市: 深交所官方静态公开 PCF XML 直连 (reportdocs.static.szse.cn)
- 沪市: 上交所官方 ETF 规模与盘前新增直连 (query.sse.com.cn)
"""
import requests
import xml.etree.ElementTree as ET
import datetime
import os
import sys

DEFAULT_WEBHOOK = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=35698b2f-960f-4ce8-b7bb-a4ac60888d9d'
WECHAT_WEBHOOK = os.getenv('WECHAT_WEBHOOK') or DEFAULT_WEBHOOK

# 核心纳指与标普500跨境ETF监控池
MONITOR_POOL = [
    # --- 深市标的 (SZSE 官方直连) ---
    {"code": "159509", "name": "景顺纳指科技", "market": "SZ", "category": "纳指"},
    {"code": "159501", "name": "嘉实纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159513", "name": "大成纳指100",  "market": "SZ", "category": "纳指"},
    {"code": "159632", "name": "华安纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159659", "name": "招商纳指100",  "market": "SZ", "category": "纳指"},
    {"code": "159660", "name": "汇添富纳指",   "market": "SZ", "category": "纳指"},
    {"code": "159696", "name": "易方达纳指",   "market": "SZ", "category": "纳指"},
    {"code": "159941", "name": "广发纳指ETF",  "market": "SZ", "category": "纳指"},
    {"code": "159612", "name": "国泰标普500",  "market": "SZ", "category": "标普"},
    {"code": "159655", "name": "华夏标普500",  "market": "SZ", "category": "标普"},
    {"code": "159577", "name": "汇添富美国50", "market": "SZ", "category": "美国50"},
    # --- 沪市标的 (SSE 官方直连) ---
    {"code": "513100", "name": "国泰纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513110", "name": "华泰柏瑞纳指", "market": "SH", "category": "纳指"},
    {"code": "513300", "name": "华夏纳斯达克", "market": "SH", "category": "纳指"},
    {"code": "513390", "name": "博时纳指100",  "market": "SH", "category": "纳指"},
    {"code": "513870", "name": "富国纳指ETF",  "market": "SH", "category": "纳指"},
    {"code": "513290", "name": "汇添富纳指生", "market": "SH", "category": "纳指"},
    {"code": "513500", "name": "博时标普500",  "market": "SH", "category": "标普"},
    {"code": "513650", "name": "南方标普500",  "market": "SH", "category": "标普"},
    {"code": "513850", "name": "易方达美国50", "market": "SH", "category": "美国50"},
]

def fetch_szse_pcf_official(code: str, date_str: str) -> dict:
    """深交所官方静态公开 PCF XML 直连解析"""
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
            }
    except Exception:
        pass
    return None

def fetch_sse_scale_official(date_fmt_dashed: str) -> dict:
    """上交所官方 ETF 规模查询接口 (返回全市场沪市ETF份额，单位：万份)"""
    url = "https://query.sse.com.cn/commonQuery.do"
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
        "STAT_DATE": date_fmt_dashed,
    }
    headers = {
        "Referer": "https://www.sse.com.cn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    res = {}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=6)
        if r.status_code == 200:
            for item in r.json().get('result', []):
                sec_code = item.get('SEC_CODE')
                vol = float(item.get('TOT_VOL', 0.0)) # 万份
                if sec_code:
                    res[sec_code] = vol
    except Exception:
        pass
    return res

def build_pure_text_report(trade_date: str = None) -> str:
    """构建纯文本无渲染监控报告"""
    if not trade_date:
        today = datetime.date.today()
        # 周末容错处理
        if today.weekday() >= 5:
            trade_date = "20260930"
            prev_date = "20260929"
        else:
            trade_date = today.strftime('%Y%m%d')
            prev_date = (today - datetime.timedelta(days=1)).strftime('%Y%m%d')
    else:
        # 如果指定了 20260930
        dt = datetime.datetime.strptime(trade_date, '%Y%m%d').date()
        trade_date = dt.strftime('%Y%m%d')
        prev_date = (dt - datetime.timedelta(days=1 if dt.weekday() != 0 else 3)).strftime('%Y%m%d')

    t_dashed = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    p_dashed = f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:]}"

    # 1. 抓取上交所今日与前日官方份额
    sse_today = fetch_sse_scale_official(t_dashed)
    sse_prev = fetch_sse_scale_official(p_dashed)

    lines = []
    lines.append("【08:15 盘前】美股跨境ETF申购限额官方监控")
    lines.append(f"基准日: {trade_date} | 模式: 沪深交易所官方直连")
    lines.append("-" * 38)
    lines.append("代码   简称         状态  当日上限   单户   CU")
    lines.append("-" * 38)

    for item in MONITOR_POOL:
        code = item['code']
        market = item['market']
        name = item['name']
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
                user_q = "  -   "
                cu = "  -   "
        else:
            # 沪市标的 (上交所官方直连份额清算差额)
            v_today = sse_today.get(code, 0.0)
            v_prev = sse_prev.get(code, 0.0)
            incr = v_today - v_prev if (v_today > 0 and v_prev > 0) else 0.0
            
            st = "开放" if v_today > 0 else "待查"
            quota = f"{incr:>6.0f}万" if incr > 0 else " 见公告 "
            user_q = " 见公告"
            cu = " 见公告"

        lines.append(f"{code}  {name_pad} {st} {quota} {user_q} {cu}")

    lines.append("-" * 38)
    lines.append("注: 当日上限为全市场允许累计申购总量(万份)。高溢价下9:15集合竞价秒光。")
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
    # 默认使用最近基准日运行
    trade_date = "20260930" if datetime.date.today().weekday() >= 5 else datetime.date.today().strftime('%Y%m%d')
    msg = build_pure_text_report(trade_date)
    print("=== 纯文本预览 ===")
    print(msg)
    res = send_wechat_text(msg)
    print("=== 微信推送结果 ===", res)
