import json

from rich.panel import Panel

from .constants import CONFIG_PATH
from .ui import console


def load_config() -> dict:
    """
    加载并校验 config.json 配置文件。
    """
    if not CONFIG_PATH.exists():
        console.print(Panel(
            "[bold red]❌ 未找到 config.json[/bold red]\n"
            "请先运行 [cyan]python make_config.py[/cyan] 生成配置文件。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        raise SystemExit(1)

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[bold red]❌ config.json 格式错误：[/bold red]{e}")
            input("按回车退出…")
            raise SystemExit(1)

    required_keys = ["classes", "locations", "cookies", "scheduletimes"]
    for key in required_keys:
        if key not in cfg:
            console.print(f"[bold red]❌ config.json 缺少必要字段：[/bold red][cyan]{key}[/cyan]，请重新运行 make_config.py")
            input("按回车退出…")
            raise SystemExit(1)

    return cfg
