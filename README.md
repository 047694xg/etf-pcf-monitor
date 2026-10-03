# 市场上所有纳指ETF和标普500ETF 官方PCF申购限额盘前监控引擎

## 特性说明
1. **交易所官方直连**：深交所官方静态公开 PCF XML 毫秒级直连解析，提取官方原生参数：
   - 全市场当日允许累计/净申购数量 (`NetCreationLimit`)
   - 单账户当日申购上限 (`NetCreationLimitPerUser`)
   - 最小申赎单位 (`CreationRedemptionUnit`)
2. **纯文本微信通知 (无Markdown渲染)**：采用纯文本固定对齐排版，彻底解决手机端表格挤压、折行变形问题。
3. **GitHub Actions 每日 08:15 自动定时运行**：零成本无服务器托管。

## 环境变量
- `WECHAT_WEBHOOK`: 企业微信机器人 Webhook 地址 (可在 GitHub Secrets 中配置)。
