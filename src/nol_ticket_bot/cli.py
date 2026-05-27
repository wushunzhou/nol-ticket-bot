"""
cli.py — Click CLI 入口

子命令：
  nol-bot check    打印当前 salesinfo 并退出
  nol-bot monitor  只监控开售，不购票
  nol-bot buy      跳过监控，直接购票（测试用）
  nol-bot run      完整流程：监控 → 开售 → 自动购票（默认）
"""
import json
import logging
import sys
import threading
import time

import click

from . import config
from .browser  import create_browser
from .monitor  import fetch_sales_info, poll_until_open
from .purchase import run as purchase_run


# ── 日志格式 ──────────────────────────────────────

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ── 公共选项 ──────────────────────────────────────

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="显示 DEBUG 日志")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """NOL World 抢票工具（CTF 授权版 NOL-CTF-2024-0518）"""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


# ── check ─────────────────────────────────────────

@main.command()
def check() -> None:
    """打印当前演出的 salesinfo 并退出。"""
    data = fetch_sales_info()
    if data:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        click.secho("❌ salesinfo 请求失败", fg="red")
        sys.exit(1)


# ── monitor ──────────────────────────────────────

@main.command()
def monitor() -> None:
    """持续监控开售状态，开售时打印通知后退出。"""
    click.secho(
        f"监控 goodsCode={config.GOODS_CODE}  Ctrl-C 退出",
        fg="cyan",
    )
    try:
        poll_until_open()
    except KeyboardInterrupt:
        click.echo("\n已停止")


# ── buy ───────────────────────────────────────────

@main.command()
def buy() -> None:
    """直接启动购票流程（跳过监控，适合票已开售或测试）。"""
    _run_purchase()


# ── run ───────────────────────────────────────────

@main.command()
def run() -> None:
    """完整流程：先监控开售，开售后自动购票。"""
    page = create_browser()
    click.secho("浏览器已启动，开始监控…", fg="cyan")

    sale_event = threading.Event()

    def on_open(_info: dict) -> None:
        click.secho("🎫 开售！启动购票流程", fg="green", bold=True)
        sale_event.set()

    t = threading.Thread(
        target=poll_until_open,
        kwargs={"on_open": on_open},
        daemon=True,
    )
    t.start()

    try:
        sale_event.wait()
        time.sleep(0.05)
        _do_purchase(page)
    except KeyboardInterrupt:
        click.echo("\n用户中断")
    finally:
        if not config.STOP_BEFORE_PAYMENT:
            try:
                page.quit()
            except Exception:
                pass


# ── 内部辅助 ──────────────────────────────────────

def _run_purchase() -> None:
    page = create_browser()
    try:
        _do_purchase(page)
    except KeyboardInterrupt:
        click.echo("\n用户中断")
    finally:
        if not config.STOP_BEFORE_PAYMENT:
            try:
                page.quit()
            except Exception:
                pass


def _do_purchase(page) -> None:
    log = logging.getLogger(__name__)
    success = purchase_run(page)
    if success:
        click.secho("\n✅ 购票流程完成！", fg="green", bold=True)
        if config.STOP_BEFORE_PAYMENT:
            click.echo("支付页面已就绪，请在浏览器中手动完成支付。")
            input("按 Enter 关闭浏览器…")
    else:
        click.secho("\n❌ 购票流程失败，请查看日志", fg="red")
        log.error("购票流程未完成")
