"""
purchase.py — NOL World 完整购票流程（基于真实逆向测试 2026-05-27）

已验证的真实流程：
  1. login()              → 填写账号 / 等待 Cloudflare Turnstile
  2. navigate_to_product()→ 产品页
  3. click_buy()          → 单次点击「立即购买」
  4. wait_for_interpark() → 等待页面跳转到 tickets.interpark.com/gates/partner
  5. wait_for_token_verify() → tokenVerify 完成后页面离开 gates/partner
                               (POST ent-bridge.interpark.com/x13_02/v1/bridge/tokenVerify)
  6. wait_for_queue()     → 在 Interpark 等待队列通过
  7. select_seat()        → 座位图选座（Interpark DOM 结构待测试后精化）
  8. confirm_order()      → 确认订单（STOP_BEFORE_PAYMENT 时暂停）

关键技术细节（逆向测试所得）：
  - NOL 点击购买 → 重定向 tickets.interpark.com/gates/partner?partner_token=JWT...
  - JWT 颁发者: ent-partner-account.inpk.in （ES256 签名）
  - tokenVerify: POST ent-bridge.interpark.com/x13_02/v1/bridge/tokenVerify
  - 重试策略: exponential backoff (capped at 60s)，503 时自动重试
  - Interpark waiting URL: ent-waiting-api.interpark.com
  - Global URL: ticket.globalinterpark.com
"""
import json
import logging
import time

from DrissionPage import ChromiumPage

from . import config
from .browser import cdp_eval, dismiss_dialog, wait_for_element

log = logging.getLogger(__name__)

PRODUCT_URL = (
    f"{config.BASE_URL}/{config.LANG}/ticket/genre/CONCERT"
    f"/products/{config.GOODS_CODE}?placeCode={config.PLACE_CODE}"
)
LOGIN_URL = f"{config.BASE_URL}/{config.LANG}/login"

# Interpark 相关 URL 特征
INTERPARK_GATES_URL   = "tickets.interpark.com/gates/partner"
INTERPARK_DOMAIN      = "tickets.interpark.com"
INTERPARK_GLOBAL      = "ticket.globalinterpark.com"
INTERPARK_WAITING_URL = "ent-waiting-api.interpark.com"


# ──────────────────────────────────────────────────
# Step 1：登录
# ──────────────────────────────────────────────────

def login(page: ChromiumPage) -> bool:
    log.info("导航到登录页")
    page.get(LOGIN_URL)
    time.sleep(2)

    if config.NOL_EMAIL and config.NOL_PASSWORD:
        try:
            wait_for_element(page, "input[type='email']", timeout=10).input(
                config.NOL_EMAIL, clear=True
            )
            wait_for_element(page, "input[type='password']", timeout=5).input(
                config.NOL_PASSWORD, clear=True
            )
            log.info("账号已填写，等待人工完成 Cloudflare Turnstile…")
        except Exception as e:
            log.warning("自动填写失败: %s", e)
    else:
        log.info("未配置账号，请在浏览器中手动登录（最多 120s）")

    for _ in range(120):
        if "login" not in page.url:
            log.info("登录成功，当前页: %s", page.url)
            return True
        time.sleep(1)

    log.error("登录超时")
    return False


# ──────────────────────────────────────────────────
# Step 2：产品页
# ──────────────────────────────────────────────────

def navigate_to_product(page: ChromiumPage) -> None:
    log.info("导航到产品页: %s", PRODUCT_URL)
    page.get(PRODUCT_URL)
    time.sleep(2)
    dismiss_dialog(page)


# ──────────────────────────────────────────────────
# Step 3：点击购买（单次）
# ──────────────────────────────────────────────────

def click_buy(page: ChromiumPage) -> bool:
    """
    点击「立即购买」按钮（单次即可，真实测试确认）。
    先用 ele.click()，失败则降级到 CDP Runtime.evaluate。
    """
    log.info("寻找「立即购买」按钮…")
    try:
        btn = wait_for_element(page, "text:立即购买", timeout=config.PAGE_WAIT_TIMEOUT)
        btn.click()
        log.info("✅ 已点击「立即购买」")
        time.sleep(0.5)
        return True
    except Exception:
        pass

    # CDP 降级：直接调用页面 JS
    log.info("ele.click() 失败，CDP 降级点击…")
    result = cdp_eval(
        page,
        "(() => { "
        "  const btn = [...document.querySelectorAll('button')]"
        "    .find(b => b.textContent.trim() === '立即购买');"
        "  if (btn) { btn.click(); return true; } return false;"
        "})()"
    )
    if result:
        log.info("✅ CDP 降级点击成功")
        time.sleep(0.5)
        return True

    log.warning("❌ 找不到「立即购买」按钮")
    return False


# ──────────────────────────────────────────────────
# Step 4：等待跳转到 Interpark gates
# ──────────────────────────────────────────────────

def wait_for_interpark(page: ChromiumPage, timeout: int = 15) -> bool:
    """
    等待页面导航到 tickets.interpark.com/gates/partner。
    点击购买后 NOL World 会立即 302 重定向。
    """
    log.info("等待 Interpark gates/partner 跳转（最多 %ds）…", timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if INTERPARK_GATES_URL in page.url or INTERPARK_DOMAIN in page.url:
            log.info("✅ 已到达 Interpark: %s", page.url[:80])
            return True
        time.sleep(0.3)
    log.warning("等待 Interpark 跳转超时，当前: %s", page.url)
    return False


# ──────────────────────────────────────────────────
# Step 5：等待 tokenVerify 完成
# ──────────────────────────────────────────────────

def wait_for_token_verify(page: ChromiumPage) -> bool:
    """
    等待 Interpark gates/partner 的 tokenVerify 完成并离开该页面。

    技术细节：
      - 调用: POST ent-bridge.interpark.com/x13_02/v1/bridge/tokenVerify
      - 503 时自动指数退避重试（页面内部 an() 函数，cap=60s）
      - 成功后页面导航到实际队列/座位页（URL 待演出日测试确定）
      - 失败时显示「정상적인 접근이 아닙니다」（异常访问，请重新开始）

    等待逻辑：
      - 监控 URL 是否离开 gates/partner
      - 或出现错误文字则认为验证失败
    """
    log.info("等待 tokenVerify 完成（最多 %ds）…", config.QUEUE_TIMEOUT)
    deadline = time.time() + config.QUEUE_TIMEOUT

    while time.time() < deadline:
        cur = page.url

        # 已离开 gates/partner → tokenVerify 成功
        if INTERPARK_GATES_URL not in cur and (
            INTERPARK_DOMAIN in cur or INTERPARK_GLOBAL in cur
        ):
            log.info("✅ tokenVerify 完成，页面跳转到: %s", cur[:100])
            return True

        # 检测错误状态
        try:
            body_text = page.ele("tag:body", timeout=0.5)
            if body_text:
                text = body_text.text or ""
                if "정상적인 접근이 아닙니다" in text or "abnormal" in text.lower():
                    log.error("❌ Interpark 报告异常访问，tokenVerify 失败")
                    return False
                if "처음부터 다시" in text:
                    log.error("❌ Interpark 要求重新开始")
                    return False
        except Exception as e:
            log.debug("body 文字检测失败: %s", e)

        time.sleep(2)

    log.warning("❌ tokenVerify 等待超时（%ds），当前: %s", config.QUEUE_TIMEOUT, page.url[:80])
    return False


# ──────────────────────────────────────────────────
# Step 6：Interpark 队列等待
# ──────────────────────────────────────────────────

def wait_for_queue(page: ChromiumPage) -> bool:
    """
    在 Interpark 侧等待队列通过。
    队列 URL 包含 waiting/queue 相关关键字，通过后跳转到选座/订单页。

    Interpark 相关 URL 特征（待演出日测试补全）：
      - 等待页: .../waiting/... 或 ent-waiting-api.interpark.com 轮询
      - 选座页: .../seat/... 或 .../booking/... 或 .../schedule/...
      - 订单页: .../order/... 或 .../payment/...
    """
    log.info("等待 Interpark 队列通过（最多 %ds）…", config.QUEUE_TIMEOUT)
    deadline = time.time() + config.QUEUE_TIMEOUT
    prev_url = page.url

    while time.time() < deadline:
        cur = page.url
        if cur != prev_url:
            log.info("页面跳转 → %s", cur[:100])
            prev_url = cur

            # 进入选座/订单页
            if any(kw in cur for kw in (
                "seat", "booking", "order", "reservation", "select",
                "schedule", "payment", "purchase"
            )):
                log.info("✅ 队列通过，进入选座/订单页")
                return True

        # Interpark 等待页可能显示当前队列号
        try:
            queue_el = page.ele("css:[class*='waiting'],[class*='queue'],[class*='rank']", timeout=0.5)
            if queue_el:
                log.info("队列进行中: %s", queue_el.text[:60])
        except Exception:
            pass

        time.sleep(config.QUEUE_POLL)

    log.warning("队列等待超时，当前页: %s", page.url[:80])
    return False


# ──────────────────────────────────────────────────
# Step 7：选座（Interpark DOM，待实测精化）
# ──────────────────────────────────────────────────

def select_seat(page: ChromiumPage) -> bool:
    """
    按 SEAT_GRADE_PREFERENCE 依次尝试在 Interpark 座位图选座。

    注意：Interpark 座位图 CSS 选择器待演出日实测后精化。
    当前使用通用探测策略（data-grade / aria-label / SVG rect）。
    """
    log.info("开始自动选座，偏好等级: %s", config.SEAT_GRADE_PREFERENCE)
    time.sleep(2)
    selected = 0

    for grade in config.SEAT_GRADE_PREFERENCE:
        if selected >= config.MAX_TICKETS:
            break
        log.info("尝试选 %s 区…", grade)

        probe_js = f"""
(function() {{
    const sels = [
        '[data-grade*="{grade}" i]:not([disabled]):not(.sold-out)',
        '[data-seatgrade*="{grade}" i]',
        '[class*="available"][class*="{grade.lower()}"]',
        '[aria-label*="{grade}"][aria-disabled="false"]',
        'rect[data-grade*="{grade}" i]',
        'text[data-grade*="{grade}" i]',
    ];
    for (const s of sels) {{
        const els = document.querySelectorAll(s);
        if (els.length) return {{ found: true, selector: s, count: els.length }};
    }}
    return {{ found: false }};
}})()
"""
        info = cdp_eval(page, probe_js) or {}
        if not info.get("found"):
            log.debug("未找到 %s 区可用座位", grade)
            continue

        sel   = info["selector"]
        count = info["count"]
        log.info("找到 %d 个 %s 区座位（%s）", count, grade, sel)

        sel_json = json.dumps(sel)  # 防止选择器含引号导致 JS 语法错误
        for i in range(min(config.MAX_TICKETS - selected, count)):
            cdp_eval(page, f"""
(function() {{
    const els = document.querySelectorAll({sel_json});
    if (els[{i}]) {{ els[{i}].click(); return true; }}
    return false;
}})()
""")
            selected += 1
            log.info("已选 %d/%d 张", selected, config.MAX_TICKETS)
            time.sleep(0.3)

    if selected == 0:
        log.warning("未找到可用座位，请在演出日检查 Interpark 座位图 HTML 结构并更新选择器")
        return False

    log.info("选座完成，共 %d 张", selected)
    return True


# ──────────────────────────────────────────────────
# Step 8：确认订单
# ──────────────────────────────────────────────────

def confirm_order(page: ChromiumPage) -> bool:
    confirm_texts = ["결제하기", "확인", "다음", "Confirm", "Next", "立即付款", "购买"]
    for text in confirm_texts:
        btn = page.ele(f"text:{text}", timeout=2)
        if btn:
            log.info("找到确认按钮「%s」", text)
            break
    else:
        log.warning("找不到确认按钮，当前页: %s", page.url[:80])
        return False

    if config.STOP_BEFORE_PAYMENT:
        log.info("=" * 55)
        log.info("STOP_BEFORE_PAYMENT=true，在此停止")
        log.info("请在浏览器中手动完成支付")
        log.info("当前页面: %s", page.url)
        log.info("=" * 55)
        return True

    btn.click()
    log.info("已点击确认，进入支付页")
    time.sleep(2)
    return True


# ──────────────────────────────────────────────────
# 全流程入口
# ──────────────────────────────────────────────────

def run(page: ChromiumPage) -> bool:
    """
    执行完整购票流程，返回 True 表示到达确认/支付页。

    真实流程（已通过 live 测试验证）：
      NOL World → 点击购买 → Interpark gates/partner
        → tokenVerify (ent-bridge.interpark.com, POST, 503时重试)
        → Interpark 队列/选座/订单
    """
    # Step 1：检查登录态（通过 /api/users/enter 401 判断，或 nav 中的用户头像）
    page.get(config.BASE_URL)
    time.sleep(1.5)
    # 优先检查 nav 中带 href 的用户相关链接（登录后才有）
    logged_in = (
        page.ele("css:a[href*='/mypage'],a[href*='/profile'],a[href*='/account']", timeout=3)
        or page.ele("css:[data-testid='user-avatar'],[data-testid='user-menu']", timeout=1)
    )
    if not logged_in:
        log.info("未检测到登录态，启动登录流程")
        if not login(page):
            return False

    # Step 2：产品页
    navigate_to_product(page)

    # Step 3：点击购买（单次）
    if not click_buy(page):
        return False
    time.sleep(1.0)

    # 如果被重定向到登录页
    if "login" in page.url:
        log.warning("被重定向到登录页，重新登录")
        if not login(page):
            return False
        navigate_to_product(page)
        dismiss_dialog(page)
        if not click_buy(page):
            return False
        time.sleep(1.0)

    # Step 4：等待到达 Interpark
    if not wait_for_interpark(page):
        log.error("未能到达 Interpark，可能被拦截或弹窗阻断")
        return False

    # Step 5：等待 tokenVerify 完成（503时页面内部自动重试）
    log.info("Interpark tokenVerify 进行中，503 时会自动指数退避重试…")
    if not wait_for_token_verify(page):
        log.error("tokenVerify 未完成（可能：账号未完成 KYC、bridge 服务异常）")
        return False

    # Step 6：等待队列通过
    if not wait_for_queue(page):
        log.error("队列等待超时，中止流程")
        return False

    # Step 7：选座
    if not select_seat(page):
        log.error("自动选座失败")
        return False

    # Step 8：确认
    return confirm_order(page)
