# nol-ticket-bot

NOL World 自动抢票工具（CTF 授权版 NOL-CTF-2024-0518）

> 授权方：Jayden.H. Kim，CTO of Nol Universe Co., Ltd.  
> 逆向测试完成：2026-05-27

---

## 安装

```bash
# 推荐：虚拟环境
python3 -m venv .venv && source .venv/bin/activate

pip install -e .
```

## 配置

```bash
cp .env.example .env
# 编辑 .env，填写演出代码和账号
```

| 变量 | 说明 |
|------|------|
| `GOODS_CODE` | 演出商品代码（产品页 URL 中） |
| `PLACE_CODE` | 场馆代码（URL 中 `placeCode=...`） |
| `BIZ_CODE` | 业务代码（默认 `10965`） |
| `NOL_EMAIL` / `NOL_PASSWORD` | 账号（留空则手动登录） |
| `SEAT_GRADE_PREFERENCE` | 选座等级优先级，逗号分隔（如 `VIP,R,S,A`） |
| `STOP_BEFORE_PAYMENT` | `true` = 到支付前停止，人工确认 |
| `QUEUE_TIMEOUT` | 队列等待超时（秒，默认 600） |
| `POLL_INTERVAL` | salesinfo 轮询间隔（秒，默认 1.5） |

## 前置条件：实名认证（必须）

购买 **Verified Member Only** 场次前，必须完成护照实名认证（ARGOS AI）：

1. 登录 NOL World → 账号页 → 点击「Verified Member Only」
2. 用手机扫描弹出的二维码
3. 完成 ARGOS 认证（护照正面 + 本人自拍）
4. 等待人工审核（最多 24 小时）
5. 审核通过后，`enterEkyc.status` 变为 `"approved"`，购票流程方可推进

> ⚠️ 认证结果与护照永久绑定，同一护照只能绑一个账号，封号无法恢复。

## 使用

```bash
# 查看当前开售状态（公开接口，无需登录）
nol-bot check

# 只监控（不购票）
nol-bot monitor

# 直接购票（跳过监控，适合票已开售或测试）
nol-bot buy

# 完整流程：监控 → 开售 → 自动购票（推荐）
nol-bot run
```

---

## 项目结构

```
src/nol_ticket_bot/
├── __init__.py
├── config.py     .env 读取与常量定义
├── monitor.py    salesinfo 轮询（无需登录）
├── browser.py    DrissionPage CDP 工厂 + 工具函数
├── purchase.py   完整购票流程（login→interpark→tokenVerify→queue→seat→confirm）
└── cli.py        Click 子命令入口
tests/
└── test_monitor.py   salesinfo 冒烟测试（responses mock，3 cases 全通过）
```

---

## 已验证的真实购票流程（2026-05-27 实测）

```
NOL World 产品页
  └─ 点击「立即购买」（单次，无需双击）
       │
       └─ 302 重定向 → tickets.interpark.com/gates/partner
              ?partner_token=JWT（ES256，3h 有效，颁发者 ent-partner-account.inpk.in）
              &partner_token_r=JWT（6h 有效）
              &gc={goodsCode}&pc={placeCode}&bc={bizCode}
              &cc=gates_global&lg=zh&user_id={encrypted}
              │
              └─ POST ent-bridge.interpark.com/x13_02/v1/bridge/tokenVerify
                     ├─ 200 → 进入 Interpark 队列/选座流程
                     ├─ 503 → 脚本自动等待指数退避重试（内置，cap 60s）
                     └─ 失败 → 「정상적인 접근이 아닙니다」
              │
              └─ Interpark 队列（ent-waiting-api.interpark.com）
              │
              └─ 选座（Interpark 座位图，CSS 选择器待演出日实测）
              │
              └─ 确认订单
                     └─ STOP_BEFORE_PAYMENT=true → 停止，人工在浏览器支付
```

---

## 技术说明

| 技术 | 说明 |
|------|------|
| **DrissionPage + CDP** | 直连 Chrome，`navigator.webdriver` 默认 `undefined`，绕过 Cloudflare Bot Management |
| **isTrusted 策略** | 优先 `ele.click()`（CDP 鼠标事件）；关键步骤用 `cdp_eval()` 直接调用页面内部函数 |
| **Cloudflare Turnstile** | 登录页人工完成（约 5–10 秒），之后全自动 |
| **partner_token** | NOL 服务端生成的 ES256 JWT，有效期 3h，携带加密的 `partner_info` |
| **tokenVerify** | Interpark bridge 验证 JWT，要求账号 eKYC 已通过；503 时脚本自动等待 |
| **salesinfo API** | 公开 REST 端点，无限制轮询；开售前自动加速到 0.3s |

---

## 已知 TODO

- [ ] 演出日实测 tokenVerify 成功后的跳转 URL，收紧 `wait_for_token_verify()` 匹配条件
- [ ] 实测 Interpark 座位图 CSS 选择器（`select_seat()` 当前使用通用探测策略）
- [ ] 记录队列通过后的实际跳转 URL，精化 `wait_for_queue()` 关键字
- [ ] 可选：集成 CapSolver 自动化 Cloudflare Turnstile（登录步骤全自动化）
