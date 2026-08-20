from rich import box
from rich.console import Console
from rich.table import Table

console = Console()

ASCII_ART = """
                     _                _____   _                     _        ____         _   __  __   ______ 
     /\\             | |              / ____| | |                   | |      |  _ \\       | | |  \\/  | |  ____|
    /  \\     _   _  | |_    ___     | |      | |__     ___    ___  | | __   | |_) |      | | | \\  / | | |__   
   / /\\ \\   | | | | | __|  / _ \\    | |      | '_ \\   / _ \\  / __| | |/ /   |  _ <   _   | | | |\\/| | |  __|  
  / ____ \\  | |_| | | |_  | (_) |   | |____  | | | | |  __/ | (__  |   <    | |_) | | |__| | | |  | | | |     
 /_/    \\_\\  \\__,_|  \\__|  \\___/     \\_____| |_| |_|  \\___|  \\___| |_|\\_\\   |____/   \\____/  |_|  |_| |_|     
                                                                                                              
                                                                                                              
 """


def print_banner():
    """打印 AutoCheckBJMF 横幅。"""
    console.print(f"\n[bold cyan]{ASCII_ART}[/bold cyan]")
    console.print()


def print_runtime_summary(
    classes: list,
    cookies: list,
    locations: list,
    pushplus_token: str,
    feishu_webhook: str,
    debug: bool,
    schedule_times: list | None = None,
):
    """打印运行配置摘要。"""
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("项目", style="bold cyan", no_wrap=True)
    table.add_column("值", style="white")
    table.add_row("班级 ID", ", ".join(classes) if classes else "[red]未配置[/red]")
    table.add_row("账号数", str(len(cookies)))
    table.add_row("定位点数", str(len(locations)))
    if schedule_times is not None:
        if schedule_times:
            table.add_row("定时时间", "[cyan]" + "  /  ".join(schedule_times) + "[/cyan]")
        else:
            table.add_row("定时时间", "[yellow]未设置（立即执行）[/yellow]")
    table.add_row("PushPlus", "[green]已配置[/green]" if pushplus_token else "[dim]未配置[/dim]")
    table.add_row("飞书 Webhook", "[green]已配置[/green]" if feishu_webhook else "[dim]未配置[/dim]")
    table.add_row("调试模式", "[yellow]开启[/yellow]" if debug else "[dim]关闭[/dim]")
    console.print(table)
