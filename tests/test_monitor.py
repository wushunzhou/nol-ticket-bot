"""
tests/test_monitor.py — salesinfo 接口冒烟测试
运行：pytest tests/
"""
import responses
import pytest

from nol_ticket_bot.monitor import fetch_sales_info, SALESINFO_URL
from nol_ticket_bot import config


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
