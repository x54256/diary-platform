"""定期回顾自然周期计算。"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


REVIEW_TIMEZONE = ZoneInfo("Asia/Shanghai")
IMPLEMENTED_REVIEW_TYPES = ("WEEK", "MONTH")


class ReviewPeriodError(ValueError):
    """周期参数不合法。"""


@dataclass(frozen=True)
class ReviewPeriod:
    review_type: str
    start: date
    end: date


def week_bounds(value: date) -> tuple[date, date]:
    start = value - timedelta(days=value.weekday())
    return start, start + timedelta(days=6)


def month_bounds(value: date) -> tuple[date, date]:
    start = value.replace(day=1)
    end = value.replace(day=calendar.monthrange(value.year, value.month)[1])
    return start, end


def period_bounds(review_type: str, period_start: date) -> ReviewPeriod:
    kind = review_type.upper()
    if kind == "WEEK":
        start, end = week_bounds(period_start)
        if start != period_start:
            raise ReviewPeriodError("周回顾的周期起始日期必须是周一")
    elif kind == "MONTH":
        start, end = month_bounds(period_start)
        if start != period_start:
            raise ReviewPeriodError("月回顾的周期起始日期必须是每月一日")
    else:
        raise ReviewPeriodError("当前只支持周回顾和月回顾")
    return ReviewPeriod(kind, start, end)


def previous_period(period: ReviewPeriod) -> ReviewPeriod:
    if period.review_type == "WEEK":
        return period_bounds("WEEK", period.start - timedelta(days=7))
    previous_month_last_day = period.start - timedelta(days=1)
    start, _ = month_bounds(previous_month_last_day)
    return period_bounds("MONTH", start)


def first_generation_time(period: ReviewPeriod) -> datetime:
    """返回周期最早允许首次生成的北京时间。"""
    if period.review_type == "WEEK":
        next_day = period.end + timedelta(days=1)
        return datetime.combine(next_day, time(2, 0), tzinfo=REVIEW_TIMEZONE)

    # 月回顾要等包含月末日期的自然周结束，再于周一 02:00 开始。
    _, containing_week_end = week_bounds(period.end)
    next_day = containing_week_end + timedelta(days=1)
    return datetime.combine(next_day, time(2, 0), tzinfo=REVIEW_TIMEZONE)


def is_generation_due(period: ReviewPeriod, now: datetime | None = None) -> bool:
    current = now or datetime.now(REVIEW_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=REVIEW_TIMEZONE)
    else:
        current = current.astimezone(REVIEW_TIMEZONE)
    return current >= first_generation_time(period)


def recent_completed_periods(
    review_type: str,
    *,
    now: datetime | None = None,
    limit: int = 24,
) -> list[ReviewPeriod]:
    """为任务中心提供最近已满足时间边界的自然周期。"""
    if limit <= 0:
        return []
    current = (now or datetime.now(REVIEW_TIMEZONE)).astimezone(REVIEW_TIMEZONE)
    kind = review_type.upper()
    if kind == "WEEK":
        start, _ = week_bounds(current.date())
        cursor = period_bounds("WEEK", start - timedelta(days=7))
    elif kind == "MONTH":
        current_month_start, _ = month_bounds(current.date())
        previous_month_last = current_month_start - timedelta(days=1)
        previous_month_start, _ = month_bounds(previous_month_last)
        cursor = period_bounds("MONTH", previous_month_start)
    else:
        raise ReviewPeriodError("当前只支持周回顾和月回顾")

    result: list[ReviewPeriod] = []
    while len(result) < limit:
        if is_generation_due(cursor, current):
            result.append(cursor)
        cursor = previous_period(cursor)
    return result
