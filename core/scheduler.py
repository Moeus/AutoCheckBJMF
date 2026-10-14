import math
import re
import time
from datetime import datetime, timedelta

from .timezone import BEIJING_TZ, TIMEZONE_LABEL, as_beijing, beijing_now


def normalize_schedule_time(value: str) -> str | None:
    """兼容中文冒号、空格和单位数输入，统一为 HH:MM。"""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("：", ":").replace("﹕", ":")
    match = re.fullmatch(r"(\d{1,2})\s*[:\s]\s*(\d{1,2})", text)
    if not match:
        return None
    hour, minute = map(int, match.groups())
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None


def validate_schedule_config(cfg: dict) -> None:
    """校验并规范化生效的配置；新区间字段优先于旧时间点。"""
    if "schedule_windows" in cfg:
        windows = cfg["schedule_windows"]
        if not isinstance(windows, list):
            raise ValueError("schedule_windows 必须是列表")
        for index, window in enumerate(windows, 1):
            if not isinstance(window, dict):
                raise ValueError(f"第 {index} 个时间区间必须是对象")
            start = normalize_schedule_time(window.get("start"))
            end = normalize_schedule_time(window.get("end"))
            interval = window.get("interval_seconds")
            if not start or not end or start == end:
                raise ValueError(f"第 {index} 个区间的起止时间须为不同的 HH:MM 时间")
            if type(interval) is not int or interval <= 0:
                raise ValueError(f"第 {index} 个区间的 interval_seconds 必须是正整数")
            window.update(start=start, end=end)
    else:
        times = cfg.get("scheduletimes", [])
        if not isinstance(times, list):
            raise ValueError("scheduletimes 必须是列表")
        normalized = [normalize_schedule_time(value) for value in times]
        if any(value is None for value in normalized):
            raise ValueError("scheduletimes 中的时间必须为 HH:MM")
        cfg["scheduletimes"] = normalized


def format_schedule_window(window: dict) -> str:
    overnight = "（次日）" if window["end"] < window["start"] else ""
    return f"{window['start']}–{window['end']}{overnight}，每 {window['interval_seconds']} 秒"


def schedule_descriptions(cfg: dict) -> list[str]:
    if "schedule_windows" in cfg:
        return [format_schedule_window(window) for window in cfg["schedule_windows"]]
    return cfg.get("scheduletimes", [])


class DailyScheduler:
    """北京时间调度：固定起点、串行执行、跳过过期时刻。"""

    def __init__(self, cfg: dict, now: datetime | None = None):
        self.windows = cfg.get("schedule_windows")
        self.times = cfg.get("scheduletimes", []) if self.windows is None else []
        self.next_run, self.valid_until = self._next(now or beijing_now())

    @staticmethod
    def _at(day, value: str) -> datetime:
        hour, minute = map(int, value.split(":"))
        return datetime.combine(day, datetime.min.time(), tzinfo=BEIJING_TZ).replace(hour=hour, minute=minute)

    def _next(self, now: datetime, strict: bool = False):
        now = as_beijing(now)
        candidates = []
        # 昨天起始的区间可能跨午夜；明天起始的区间确保每天循环。
        for offset in (-1, 0, 1):
            day = now.date() + timedelta(days=offset)
            for window in self.windows or []:
                start = self._at(day, window["start"])
                end = self._at(day, window["end"])
                if end <= start:
                    end += timedelta(days=1)
                interval = window["interval_seconds"]
                elapsed = (now - start).total_seconds()
                step = max(0, math.floor(elapsed / interval) + 1 if strict else math.ceil(elapsed / interval))
                # 先比较步数，避免过大的合法间隔造成 timedelta 溢出。
                if step * interval >= (end - start).total_seconds():
                    continue
                target = start + timedelta(seconds=step * interval)
                valid_until = target + timedelta(seconds=min(interval, (end - target).total_seconds()))
                candidates.append((target, valid_until))
            for value in self.times:
                target = self._at(day, value)
                if target > now or (target == now and not strict):
                    candidates.append((target, target + timedelta(days=1)))
        if not candidates:
            return None, None
        target = min(item[0] for item in candidates)
        # 多个区间同一时刻只执行一轮，其中任一区间仍有效即可。
        return target, max(end for start, end in candidates if start == target)

    def is_due(self, now: datetime) -> bool:
        now = as_beijing(now)
        if self.next_run is not None and now >= self.valid_until:
            self.next_run, self.valid_until = self._next(now)
        return self.next_run is not None and now >= self.next_run

    def advance(self, now: datetime) -> None:
        """一轮结束后重新计算，既不补跑也不积累执行耗时。"""
        self.next_run, self.valid_until = self._next(now, strict=True)


def get_countdown_status(next_run: datetime | list, now: datetime | None = None) -> tuple[str, int]:
    """倒计时使用调度器的下一次执行时间，保留旧列表调用。"""
    now = as_beijing(now) if now is not None else beijing_now()
    if isinstance(next_run, list):
        next_run = DailyScheduler({"scheduletimes": next_run}, now).next_run
    if next_run is None:
        return "未配置定时任务", 1
    next_run = as_beijing(next_run)
    remaining = max(0, math.ceil((next_run - now).total_seconds()))
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    text = (
        f"⏰ {TIMEZONE_LABEL} [dim]{now:%Y-%m-%d %H:%M:%S}[/dim] │ "
        f"下次任务 [bold cyan]{next_run:%m-%d %H:%M:%S}[/bold cyan] │ "
        f"剩余 [bold yellow]{hours} 小时 {minutes} 分 {seconds} 秒[/bold yellow]"
    )
    return text, 1 if remaining < 300 else 60


def show_countdown(schedule_times: list):
    from .ui import console

    text, delay = get_countdown_status(schedule_times)
    console.print(text)
    time.sleep(delay)
