"""中国节假日年度数据获取、解析和缓存。"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

import httpx
from sqlalchemy.orm import Session

from models.schedule import ScheduleHolidayYear

logger = logging.getLogger("app.schedule_holidays")
HOLIDAY_URL = "https://timor.tech/api/holiday/year/{year}"
HOLIDAY_RETRY_INTERVAL = timedelta(days=30)
HOLIDAY_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
}


def _classify_entry(entry: dict) -> tuple[set[date], set[date]]:
    workdays: set[date] = set()
    restdays: set[date] = set()
    value = entry.get("date")
    if value:
        target = date.fromisoformat(value)
        if entry.get("after") is True or (entry.get("wage") == 1 and entry.get("after") is True):
            workdays.add(target)
        elif entry.get("holiday") is True or entry.get("wage") in (2, 3):
            restdays.add(target)
    return workdays, restdays


def parse_holiday_payload(payload: dict, year: int) -> tuple[set[date], set[date]]:
    workdays: set[date] = set()
    restdays: set[date] = set()
    holidays = payload.get("holiday") if isinstance(payload, dict) else None
    values = holidays.values() if isinstance(holidays, dict) else holidays if isinstance(holidays, list) else []
    for holiday in values:
        if not isinstance(holiday, dict):
            continue
        current_workdays, current_restdays = _classify_entry(holiday)
        workdays.update(current_workdays)
        restdays.update(current_restdays)
        entries = holiday.get("list") or []
        for entry in entries:
            if isinstance(entry, dict):
                current_workdays, current_restdays = _classify_entry(entry)
                workdays.update(current_workdays)
                restdays.update(current_restdays)
    workdays = {value for value in workdays if value.year == year}
    restdays = {value for value in restdays if value.year == year and value not in workdays}
    return workdays, restdays


def refresh_holiday_year(db: Session, year: int) -> ScheduleHolidayYear:
    cached = db.query(ScheduleHolidayYear).filter_by(year=year).first()
    if cached and cached.is_available:
        return cached
    now = datetime.utcnow()
    if cached and cached.fetched_at and now - cached.fetched_at < HOLIDAY_RETRY_INTERVAL:
        return cached
    try:
        response = httpx.get(
            HOLIDAY_URL.format(year=year),
            timeout=10,
            follow_redirects=True,
            headers=HOLIDAY_REQUEST_HEADERS,
        )
        response.raise_for_status()
        workdays, restdays = parse_holiday_payload(response.json(), year)
        available = bool(workdays or restdays)
    except Exception:
        logger.exception(
            "获取节假日年度数据失败 year=%s，下次重试时间=%s",
            year,
            now + HOLIDAY_RETRY_INTERVAL,
        )
        workdays, restdays, available = set(), set(), False
    if not cached:
        cached = ScheduleHolidayYear(year=year)
        db.add(cached)
    cached.is_available = available
    cached.workdays = json.dumps(sorted(value.isoformat() for value in workdays), ensure_ascii=False)
    cached.restdays = json.dumps(sorted(value.isoformat() for value in restdays), ensure_ascii=False)
    cached.fetched_at = now
    return cached


def ensure_holiday_years(db: Session, years: Iterable[int]) -> None:
    for year in sorted(set(years)):
        refresh_holiday_year(db, year)


def holiday_sets(db: Session, years: Iterable[int]) -> tuple[set[date], set[date]]:
    workdays: set[date] = set()
    restdays: set[date] = set()
    for year in sorted(set(years)):
        cached = db.query(ScheduleHolidayYear).filter_by(year=year).first()
        if not cached or not cached.is_available:
            continue
        workdays.update(date.fromisoformat(value) for value in json.loads(cached.workdays))
        restdays.update(date.fromisoformat(value) for value in json.loads(cached.restdays))
    return workdays, restdays
