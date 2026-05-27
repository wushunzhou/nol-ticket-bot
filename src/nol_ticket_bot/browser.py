"""
browser.py — DrissionPage 浏览器工厂与 CDP 工具函数

核心反检测策略：
  - DrissionPage 使用 CDP 协议（非 WebDriver），navigator.webdriver 默认 undefined
  - 启动时注入脚本确保所有新 Document 也看不到 webdriver 标记
"""
import logging
import time
from typing import Any

from DrissionPage import ChromiumPage, ChromiumOptions

from . import config

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────
# 浏览器工厂
# ──────────────────────────────────────────────────

def create_browser() -> ChromiumPage:
    co = ChromiumOptions()

    # 反自动化检测
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_pref("credentials_enable_service", False)
    co.set_pref("profile.password_manager_enabled", False)

    co.set_argument(f"--window-size={config.WINDOW_W},{config.WINDOW_H}")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")

    if config.CHROMIUM_PATH:
        co.set_browser_path(config.CHROMIUM_PATH)

    if config.HEADLESS:
        co.headless(True)

    page = ChromiumPage(co)

    # 对所有新 Document 注入：覆盖 navigator.webdriver → undefined
    page.run_cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        source="""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true,
            });
        """,
    )

    log.info("浏览器已启动（headless=%s）", config.HEADLESS)
    return page


# ──────────────────────────────────────────────────
# CDP 工具
# ──────────────────────────────────────────────────

def cdp_eval(page: ChromiumPage, js: str) -> Any:
    """
    通过 CDP Runtime.evaluate 执行 JS，返回结果值。
    用于直接调用页面内部函数——完全绕过 isTrusted 事件检测。
    """
    result = page.run_cdp(
        "Runtime.evaluate",
        expression=js,
        returnByValue=True,
        awaitPromise=True,
    )
    return result.get("result", {}).get("value")


def wait_for_element(page: ChromiumPage, selector: str, timeout: int = config.PAGE_WAIT_TIMEOUT):
    """等待元素出现，超时抛出 TimeoutError。"""
    start = time.time()
    while time.time() - start < timeout:
        el = page.ele(selector, timeout=1)
        if el:
            return el
        time.sleep(0.2)
    raise TimeoutError(f"超时：找不到元素 {selector!r}")


def dismiss_dialog(page: ChromiumPage) -> bool:
    """关闭 NOL 公告弹窗（「关闭」按钮）。"""
    btn = page.ele("text:关闭", timeout=3)
    if btn:
        btn.click()
        log.debug("已关闭公告弹窗")
        time.sleep(0.4)
        return True
    return False
