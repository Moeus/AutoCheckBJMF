import time


def get_countdown_status(schedule_times: list) -> tuple[str, int]:
    """
    返回倒计时文本和下一次刷新间隔。
    """
    now = time.time()
    next_stamps = []
    for t_str in schedule_times:
        hour, minute = map(int, t_str.split(":"))
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        target_struct = time.strptime(f"{today} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
        stamp = time.mktime(target_struct)
        if stamp < now:
            stamp += 24 * 3600
        next_stamps.append((stamp, t_str))

    next_stamp, next_time_str = min(next_stamps, key=lambda x: x[0])
    remaining = int(next_stamp - now)

    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    current = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))

    if remaining < 300:
        text = (
            f"⏰  当前 [dim]{current}[/dim]  │  "
            f"下次任务 [bold cyan]{next_time_str}[/bold cyan]  │  "
            f"剩余 [bold yellow]{minutes}[/bold yellow] 分 [bold yellow]{seconds}[/bold yellow] 秒"
        )
        return text, 1

    text = (
        f"⏰  当前 [dim]{current}[/dim]  │  "
        f"下次任务 [bold cyan]{next_time_str}[/bold cyan]  │  "
        f"剩余 [bold yellow]{hours}[/bold yellow] 小时 [bold yellow]{minutes}[/bold yellow] 分钟"
    )
    return text, 60


def show_countdown(schedule_times: list):
    """
    兼容旧调用：打印一次倒计时并睡眠到下一次刷新。
    """
    from .ui import console

    text, delay = get_countdown_status(schedule_times)
    console.print(text)
    time.sleep(delay)
