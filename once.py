"""
once.py — AutoCheckBJMF 一次性立即签到
==========================================
应急使用：读取 config.json 配置，立即对所有班级执行一次签到，
不涉及定时调度，启动即签。

使用方式：
    python once.py

若 config.json 不存在，请先运行 make_config.py 生成配置。
"""

from rich.panel import Panel

from core.config import load_config
from core.logger import setup_logger
from core.signin import run_all_classes
from core.ui import console, print_banner, print_runtime_summary


def validate_once_config(classes: list, cookies: list, locations: list) -> bool:
    """校验一次性签到需要的基础配置。"""
    if not classes:
        console.print(Panel(
            "[bold red]❌ 未配置任何班级 ID[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return False

    if not cookies:
        console.print(Panel(
            "[bold red]❌ 未配置任何账号 Cookie[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return False

    if not locations:
        console.print(Panel(
            "[bold red]❌ 未配置任何定位点[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return False

    return True


def main():
    """
    once.py 程序入口：
    1. 加载配置文件
    2. 初始化日志
    3. 立即对所有班级、所有账号执行一次完整签到
    4. 签到结束后等待用户按回车退出
    """
    print_banner()
    console.print(Panel(
        "[bold white]AutoCheckBJMF — 班级魔方自动签到[/bold white]  [bold yellow]一次性模式[/bold yellow]\n"
        "[dim]项目地址：https://github.com/Moeus/AutoCheckBJMF[/dim]\n"
        "[bold yellow]⚡ 启动后立即签到，不进行定时等待[/bold yellow]",
        border_style="yellow", padding=(0, 4)
    ))

    cfg = load_config()
    classes = cfg["classes"]
    locations = cfg["locations"]
    cookies = cfg["cookies"]
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
    )

    if not validate_once_config(classes, cookies, locations):
        return

    run_all_classes(classes, cookies, locations, pushplus_token, debug, logger, feishu_webhook)

    console.print(Panel(
        "[bold green]✅ 一次性签到任务已完成。[/bold green]",
        border_style="green", padding=(0, 2)
    ))
    input("  按回车关闭窗口…")


if __name__ == "__main__":
    main()
