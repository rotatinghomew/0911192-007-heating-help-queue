"""共享的时间与格式工具。

交接资料中的时间均为本地时间（东八区），不附时区；空值表示资料未给出。
"""
from __future__ import annotations

from datetime import datetime


def parse_dt(text: str | None) -> datetime | None:
    text = (text or "").strip()
    return datetime.fromisoformat(text) if text else None


def hours_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0


def fmt_dt(value: datetime | None) -> str:
    return "未知" if value is None else value.isoformat()


def fmt_hours(value: float | None) -> str:
    return "未知" if value is None else f"{value:.1f}h"


def fmt_pct(value: float | None) -> str:
    return "难定" if value is None else f"{value * 100:.0f}%"
