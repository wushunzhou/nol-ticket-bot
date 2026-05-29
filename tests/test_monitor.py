"""
tests/test_monitor.py — salesinfo 接口冒烟测试
运行：pytest tests/
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import responses

from nol_ticket_bot import config
from nol_ticket_bot.monitor import KST, SALESINFO_URL, fetch_sales_info, poll_until_open


@responses.activate
def test_fetch_sales_info_success():
    """返回 200 且 body 正确时，应解析出 data 字段。"""
    responses.add(
        responses.GET,
        SALESINFO_URL,
        json={
            "data": {
                "goodsCode": config.GOODS_CODE,
                "placeCode": config.PLACE_CODE,
                "salesInfo": {"goodsStatus": "Y"},
            }
        },
        status=200,
    )
    result = fetch_sales_info()
    assert result is not None
    assert result["salesInfo"]["goodsStatus"] == "Y"


@responses.activate
def test_fetch_sales_info_network_error():
    """网络错误时应返回 None，不抛出异常。"""
    responses.add(responses.GET, SALESINFO_URL, body=ConnectionError("timeout"))
    result = fetch_sales_info()
    assert result is None


@responses.activate
def test_fetch_sales_info_500():
    """服务端 500 时应返回 None。"""
    responses.add(responses.GET, SALESINFO_URL, status=500)
    result = fetch_sales_info()
    assert result is None


# ── poll_until_open：动态加速逻辑 ─────────────────────────────

def _make_sales_response(status: str, open_time: str | None = None) -> dict:
    sales = {"goodsStatus": status}
    if open_time:
        sales["bookingOpenTime"] = open_time
    return {"data": {"goodsCode": config.GOODS_CODE, "salesInfo": sales}}


@responses.activate
def test_poll_interval_accelerates_within_30s():
    """距开售 < 30s 时轮询间隔应降到 0.5s。"""
    open_time = (datetime.now(KST) + timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S")
    # 第一次返回未开售（触发加速），第二次返回开售
    responses.add(responses.GET, SALESINFO_URL, json=_make_sales_response("N", open_time))
    responses.add(responses.GET, SALESINFO_URL, json=_make_sales_response("Y", open_time))

    intervals = []

    with patch("nol_ticket_bot.monitor.time.sleep", side_effect=lambda s: intervals.append(s)):
        poll_until_open()

    assert intervals[0] == pytest.approx(0.5), f"距开售 20s 时应加速到 0.5s，实际={intervals[0]}"


@responses.activate
def test_poll_interval_accelerates_within_5s():
    """距开售 < 5s 时轮询间隔应降到 0.3s。"""
    open_time = (datetime.now(KST) + timedelta(seconds=3)).strftime("%Y-%m-%d %H:%M:%S")
    responses.add(responses.GET, SALESINFO_URL, json=_make_sales_response("N", open_time))
    responses.add(responses.GET, SALESINFO_URL, json=_make_sales_response("Y", open_time))

    intervals = []

    with patch("nol_ticket_bot.monitor.time.sleep", side_effect=lambda s: intervals.append(s)):
        poll_until_open()

    assert intervals[0] == pytest.approx(0.3), f"距开售 3s 时应加速到 0.3s，实际={intervals[0]}"


@responses.activate
def test_poll_on_open_callback():
    """goodsStatus == 'Y' 时应调用 on_open 并传入完整 info。"""
    responses.add(responses.GET, SALESINFO_URL, json=_make_sales_response("Y"))

    callback = MagicMock()
    with patch("nol_ticket_bot.monitor.time.sleep"):
        result = poll_until_open(on_open=callback)

    callback.assert_called_once()
    assert result["salesInfo"]["goodsStatus"] == "Y"


# ── wait_for_token_verify：URL 变化判断 ──────────────────────

def _mock_page(url: str) -> MagicMock:
    page = MagicMock()
    page.url = url
    page.ele.return_value = None  # 无错误文字
    return page


def test_wait_for_token_verify_success():
    """URL 已离开 gates/partner 且在 interpark 域时应返回 True。"""
    from nol_ticket_bot.purchase import wait_for_token_verify

    page = _mock_page("https://tickets.interpark.com/seat/select?gc=26005973")
    # 不 mock time.time：函数第一次迭代即检测到 URL 已跳转，立即 return True
    result = wait_for_token_verify(page)
    assert result is True


def test_wait_for_token_verify_still_on_gates():
    """仍在 gates/partner 页时超时后应返回 False。"""
    from nol_ticket_bot.purchase import wait_for_token_verify

    page = _mock_page("https://tickets.interpark.com/gates/partner?partner_token=xxx")

    # QUEUE_TIMEOUT=-1 → deadline 在过去 → while 条件第一次就 False，立即超时
    with patch("nol_ticket_bot.config.QUEUE_TIMEOUT", new=-1):
        with patch("nol_ticket_bot.purchase.time.sleep"):
            result = wait_for_token_verify(page)

    assert result is False


def test_wait_for_token_verify_error_text():
    """检测到韩语错误文字时应立即返回 False。"""
    from nol_ticket_bot.purchase import wait_for_token_verify

    page = MagicMock()
    page.url = "https://tickets.interpark.com/gates/partner?partner_token=xxx"
    body_el = MagicMock()
    body_el.text = "정상적인 접근이 아닙니다 다시 시도해 주세요"
    page.ele.return_value = body_el

    # 不 mock time.time：第一次循环检测到错误文字，立即 return False（sleep 不会被调用）
    result = wait_for_token_verify(page)
    assert result is False
