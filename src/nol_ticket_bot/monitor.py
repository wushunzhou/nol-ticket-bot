"""
monitor.py — salesinfo 轮询
公开 REST 接口，无需登录。
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Callable

# NOL/Interpark 服务时间均为 KST (UTC+9)
KST = timezone(timedelta(hours=9))

import requests

from . import config

log = logging.getLogger(__name__)

SALESINFO_URL = f"{config.BASE_URL}/api/ent-channel-out/v1/goods/salesinfo"


def fetch_sales_info() -> dict | None:
    """
    GET /api/ent-channel-out/v1/goods/salesinfo
    返回 data 字段；网络错误时返回 None。
    """
    try:
        r = requests.get(
            SALESINFO_URL,
            params={
                "goodsCode": config.GOODS_CODE,
                "placeCode":  config.PLACE_CODE,
                "bizCode":    config.BIZ_CODE,
            },
            timeout=5,
        )
        r.raise_for_status()
        return r.json().get("data", {})
    except (requests.RequestException, OSError, Exception) as e:
        log.warning("salesinfo 请求失败: %s", e)
    return None


def poll_until_open(on_open: Callable[[dict], None] | None = None) -> dict:
    """
    持续轮询，直到 goodsStatus == 'Y'。
    - 距开售 < 30s：加速到 0.5s
    - 距开售 < 5s ：加速到 0.3s
    """
    interval = config.POLL_INTERVAL
    log.info(
        "开始监控 goodsCode=%s，初始间隔 %.1fs",
        config.GOODS_CODE, interval,
    )

    while True:
        info = fetch_sales_info()
        if info:
            sales       = info.get("salesInfo", {})
            status      = sales.get("goodsStatus", "?")
            open_time   = sales.get("bookingOpenTime", "")

            # 根据剩余时间动态调整轮询间隔
            if open_time:
                try:
                    # bookingOpenTime 为 KST，用 aware datetime 比较避免时区偏差
                    ot = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                    secs_left = (ot - datetime.now(KST)).total_seconds()
                    if secs_left <= 5:
                        interval = 0.3
                    elif secs_left <= 30:
                        interval = 0.5
                except ValueError:
                    pass

            log.info(
                "状态=%s | 开售=%s | 结束=%s",
                status, open_time, sales.get("bookingEndTime", ""),
            )

            if status == "Y":
                log.info("🎫 ===== 开售！=====")
                if on_open:
                    on_open(info)
                return info

        time.sleep(interval)
