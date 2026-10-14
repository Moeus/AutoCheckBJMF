"""
main.py — AutoCheckBJMF 定时签到主程序
==========================================
读取 config.json，每天在 schedule_windows 区间内按固定步长执行签到，
兼容旧 scheduletimes 时间点配置。

使用方式：
    python main.py

若 config.json 不存在，请先运行 make_config.py 生成配置。
"""

import time
from rich.live import Live
from rich.panel import Panel

from core.config import load_config
from core.logger import setup_logger
from core.notifications import send_lifecycle_notification
from core.scheduler import DailyScheduler, get_countdown_status, schedule_descriptions
from core.signin import run_all_classes
from core.timezone import beijing_now
from core.ui import console, print_banner, print_runtime_summary


def main():
    """
    main.py 程序入口：
    1. 加载配置文件
    2. 初始化日志
    3. 若有定时配置则循环调度并显示倒计时
    4. 若无定时时间则立即执行一次签到后退出
    """
    print_banner()
    console.print(Panel(
        "[bold white]AutoCheckBJMF — 班级魔方自动签到[/bold white]  [dim]定时模式[/dim]\n"
        "[dim]项目地址：https://github.com/Moeus/AutoCheckBJMF[/dim]",
        border_style="cyan", padding=(0, 4)
    ))

    cfg = load_config()
    classes = cfg["classes"]
    locations = cfg["locations"]
    cookies = cfg["cookies"]
    schedule_times = schedule_descriptions(cfg)
    window_mode = bool(cfg.get("schedule_windows"))
    pushplus_token = cfg.get("pushplus", "")
    feishu_webhook = cfg.get("feishu_webhook", cfg.get("feishu_websocket", ""))
    debug = cfg.get("debug", False)

    logger = setup_logger(debug)
    print_runtime_summary(
        classes=classes,
        cookies=cookies,
        locations=locations,
        pushplus_token=pushplus_token,
        feishu_webhook=feishu_webhook,
        debug=debug,
        schedule_times=schedule_times,
    )

    lifecycle_mode = "区间模式" if window_mode else ("定时模式" if schedule_times else "立即模式")
    send_lifecycle_notification(
        pushplus_token, feishu_webhook, "已启动", lifecycle_mode, logger, schedule_times
    )

    def job():
        run_all_classes(
            classes, cookies, locations, pushplus_token, debug, logger, feishu_webhook,
            retry_failures=not window_mode,
        )
        if schedule_times:
            console.print("\n  [dim]☆ 本次签到结束，继续等待下一个定时任务…[/dim]\n")

    try:
        if schedule_times:
            scheduler = DailyScheduler(cfg)
            for t_str in schedule_times:
                console.print(f"  [bold green]✔[/bold green] 已注册定时任务：每天 [bold cyan]{t_str}[/bold cyan]")

            console.print(f"\n  [bold green]★ 定时签到已启动，按 Ctrl+C 停止[/bold green]\n")
            with Live("", console=console, refresh_per_second=1, transient=True) as live:
                while True:
                    now = beijing_now()
                    if scheduler.is_due(now):
                        live.stop()
                        job()
                        scheduler.advance(beijing_now())
                        live.start()
                        continue

                    text, delay = get_countdown_status(scheduler.next_run, now)
                    live.update(text)
                    time.sleep(min(delay, 1))
        else:
            console.print("  [bold yellow]★ 未配置定时时间，立即开始签到…[/bold yellow]\n")
            job()
            input("\n  手动签到已结束，按回车关闭窗口…")
    except KeyboardInterrupt:
        console.print("\n  [yellow]已收到停止信号，准备退出…[/yellow]")
    finally:
        send_lifecycle_notification(
            pushplus_token, feishu_webhook, "已关闭", lifecycle_mode, logger, schedule_times
        )


if __name__ == "__main__":
    main()
