import json

from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML
from rich.panel import Panel

from .constants import CONFIG_PATH
from .ui import ASCII_ART, console


def print_config_banner():
    """打印配置向导横幅。"""
    console.print(f"\n[bold cyan]{ASCII_ART}[/bold cyan]")
    console.print(
        Panel.fit(
            "[bold white]班级魔方 GPS 自动签到配置向导[/bold white]\n"
            "[dim]项目地址：https://github.com/Moeus/AutoCheckBJMF[/dim]",
            border_style="cyan",
            padding=(0, 4),
        )
    )
    console.print()


def prompt_input(message: str, placeholder: str = "", default: str = "") -> str:
    """
    带灰色占位符提示的终端输入框。
    """
    placeholder_html = HTML(f'<style color="#888888">{placeholder}</style>') if placeholder else None
    result = prompt(message, placeholder=placeholder_html).strip()
    return result if result else default


def load_existing_config() -> dict:
    """
    读取已有的 config.json，若不存在则返回空字典。
    """
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_config(config: dict):
    """
    将配置字典写入 config.json。
    """
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    console.print(f"\n[bold green]✅ 配置已保存至：[/bold green][underline]{CONFIG_PATH}[/underline]")


def print_step_header(step: int, total: int, title: str, subtitle: str = ""):
    """
    打印统一风格的步骤标题面板。
    """
    step_label = f"步骤 {step}/{total}"
    content = f"[bold white]{title}[/bold white]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"
    console.print(
        Panel(
            content,
            title=f"[bold yellow] {step_label} [/bold yellow]",
            border_style="yellow",
            padding=(0, 2),
        )
    )
