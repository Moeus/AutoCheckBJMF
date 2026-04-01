"""
once.py — AutoCheckBJMF 一次性立即签到
==========================================
应急使用：读取 config.json 配置，立即对所有班级执行一次签到，
不涉及定时调度，启动即签。

使用方式：
    python once.py

若 config.json 不存在，请先运行 make_config.py 生成配置。
"""

# ─────────────────────────────────────────────────────────────
#  直接从 main.py 复用签到核心逻辑，避免代码重复
#  导入：load_config, setup_logger, run_all_classes, console
# ─────────────────────────────────────────────────────────────
from main import load_config, setup_logger, run_all_classes, console

from rich.panel import Panel
from rich.table import Table
from rich import box


def main():
    """
    once.py 程序入口：
    1. 加载配置文件（与 main.py 共用 config.json）
    2. 初始化日志（遵循 debug 配置）
    3. 立即对所有班级、所有账号执行一次完整签到
    4. 签到结束后等待用户按回车退出
    """
    console.print(Panel(
        "[bold white]AutoCheckBJMF — 班级魔方自动签到[/bold white]  [bold yellow]一次性模式[/bold yellow]\n"
        "[dim]项目地址：https://github.com/Moeus/AutoCheckBJMF[/dim]\n"
        "[bold yellow]⚡ 启动后立即签到，不进行定时等待[/bold yellow]",
        border_style="yellow", padding=(0, 4)
    ))

    # ── 加载配置 ──
    cfg = load_config()
    classes        = cfg["classes"]
    locations      = cfg["locations"]
    cookies        = cfg["cookies"]
    pushplus_token = cfg.get("pushplus", "")
    debug          = cfg.get("debug", False)

    # ── 初始化日志系统 ──
    logger = setup_logger(debug)

    # ── 打印配置摘要（Rich Table） ──
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("项目", style="bold cyan", no_wrap=True)
    table.add_column("值", style="white")
    table.add_row("班级 ID", ", ".join(classes) if classes else "[red]未配置[/red]")
    table.add_row("账号数", str(len(cookies)))
    table.add_row("定位点数", str(len(locations)))
    table.add_row("PushPlus", "[green]已配置[/green]" if pushplus_token else "[dim]未配置[/dim]")
    table.add_row("调试模式", "[yellow]开启[/yellow]" if debug else "[dim]关闭[/dim]")
    console.print(table)

    # ── 基础校验 ──
    if not classes:
        console.print(Panel(
            "[bold red]❌ 未配置任何班级 ID[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return

    if not cookies:
        console.print(Panel(
            "[bold red]❌ 未配置任何账号 Cookie[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return

    if not locations:
        console.print(Panel(
            "[bold red]❌ 未配置任何定位点[/bold red]\n请先运行 [cyan]python make_config.py[/cyan] 完成配置。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        return

    # ── 立即执行签到 ──
    run_all_classes(classes, cookies, locations, pushplus_token, debug, logger)

    console.print(Panel(
        "[bold green]✅ 一次性签到任务已完成。[/bold green]",
        border_style="green", padding=(0, 2)
    ))
    input("  按回车关闭窗口…")


if __name__ == "__main__":
    main()
