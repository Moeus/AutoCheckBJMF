"""
make_config.py — AutoCheckBJMF 配置向导
=========================================
交互式终端引导用户完成所有配置，并将结果写入 config.json。

新版配置格式：
{
    "classes":      ["123456", "789012"],        # 班级 ID 列表（支持多班级）
    "locations": [                               # 签到定位点列表（支持多个）
        {"lat": "39.90000000", "lng": "116.40000000", "acc": "10"}
    ],
    "cookies":      ["remember_student_xxx=..."], # 用户 Cookie 列表（支持多账号）
    "scheduletimes": ["08:00", "12:30"],          # 定时签到时间列表（支持多个）
    "pushplus":     "",                           # PushPlus 推送 Token（可选）
    "debug":        false                         # 调试模式
}
"""

import os
import re
import json
from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML
import questionary
from DrissionPage import ChromiumPage

# ── Rich 终端美化库 ──
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.prompt import Confirm

# 全局 Rich 控制台实例（stderr=False 保证输出到标准输出）
console = Console()

# ──────────────────────────────────────────────
#  常量定义
# ──────────────────────────────────────────────

# 配置文件保存路径（与脚本同目录）
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 微信扫码登录地址
LOGIN_URL = "https://login.b8n.cn/qr/weixin/student/2"

# 扫码后等待跳转的监听目标
LISTEN_TARGET = "https://bj.k8n.cn/student"

# 腾讯坐标拾取工具地址
MAP_URL = "https://lbs.qq.com/getPoint/"

# Cookie 中需要提取的字段名
COOKIE_KEY = "remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d"


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def print_banner():
    """打印带 Rich 样式的欢迎横幅与 ASCII Art 标题。"""
    # ASCII Art 标题（保持原有设计）
    ascii_art = """
                     _                _____   _                     _        ____         _   __  __   ______ 
     /\             | |              / ____| | |                   | |      |  _ \       | | |  \/  | |  ____|
    /  \     _   _  | |_    ___     | |      | |__     ___    ___  | | __   | |_) |      | | | \  / | | |__   
   / /\ \   | | | | | __|  / _ \    | |      | '_ \   / _ \  / __| | |/ /   |  _ <   _   | | | |\/| | |  __|  
  / ____ \  | |_| | | |_  | (_) |   | |____  | | | | |  __/ | (__  |   <    | |_) | | |__| | | |  | | | |     
 /_/    \_\  \__,_|  \__|  \___/     \_____| |_| |_|  \___|  \___| |_|\_\   |____/   \____/  |_|  |_| |_|     
                                                                                                              
                                                                                                              
 """

    console.print(f"\n[bold cyan]{ascii_art}[/bold cyan]")
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
    带灰色占位符提示的终端输入框（基于 prompt_toolkit）。

    参数：
        message     — 显示给用户的提示文字
        placeholder — 输入框内的灰色提示文字（用户一开始输入即消失）
        default     — 若用户直接回车则使用的默认值

    返回：
        用户输入的字符串（去除首尾空白），若为空则返回 default。
    """
    placeholder_html = HTML(f'<style color="#888888">{placeholder}</style>') if placeholder else None
    result = prompt(message, placeholder=placeholder_html).strip()
    return result if result else default


def load_existing_config() -> dict:
    """
    读取已有的 config.json，若不存在则返回空字典。

    返回：
        配置字典，键不存在时返回 {}。
    """
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_config(config: dict):
    """
    将配置字典写入 config.json（UTF-8，4 空格缩进）。

    参数：
        config — 完整的配置字典
    """
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    console.print(f"\n[bold green]✅ 配置已保存至：[/bold green][underline]{CONFIG_PATH}[/underline]")


def print_step_header(step: int, total: int, title: str, subtitle: str = ""):
    """
    打印统一风格的步骤标题面板。

    参数：
        step     — 当前步骤序号
        total    — 总步骤数
        title    — 步骤标题
        subtitle — 步骤副标题/说明（可选）
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


# ──────────────────────────────────────────────
#  步骤 1：通过浏览器扫码获取班级列表与 Cookie
# ──────────────────────────────────────────────

def login_and_capture(existing_cookies: list) -> tuple[list, list]:
    """
    打开浏览器引导用户微信扫码登录，自动提取课程班级 ID 和 Cookie。
    支持循环：每次扫码添加一个账号，直到用户选择不再添加。

    参数：
        existing_cookies — 已有的 Cookie 列表（用于追加，不会覆盖）

    返回：
        (class_list, cookie_list)
            class_list  — 从页面提取的所有班级 ID（字符串列表，去重）
            cookie_list — 提取到的 Cookie 字符串列表
    """
    class_set = set()                          # 用集合去重班级 ID
    cookie_list = list(existing_cookies)       # 从已有 Cookie 开始追加

    print_step_header(
        1, 4,
        "获取班级 ID 与 Cookie",
        "程序将打开浏览器，请用微信扫码登录。登录后自动提取班级 ID 和 Cookie。"
    )

    while True:
        answer = questionary.confirm("是否（继续）添加账号？（扫码登录）", default=True).ask()
        if not answer:
            break

        page = ChromiumPage()
        try:
            # 开始监听网络请求，以便捕获带 Cookie 的请求
            page.listen.start(LISTEN_TARGET)
            console.print("  [cyan]▶[/cyan] 正在打开登录页，请用微信扫码（最长等待 120 秒）…")
            page.get(LOGIN_URL)

            # 等待扫码成功后页面出现课程列表元素
            if not page.wait.eles_loaded('t:a@class=media', timeout=120):
                console.print("  [bold red]✗[/bold red] 等待登录超时，请重试。")
                page.close()
                continue

            console.print("  [bold green]✔[/bold green] 扫码登录成功！正在读取课程列表…")

            # 提取页面中所有课程链接里的班级 ID
            a_tags = page.eles('t:a@class=media')
            for a in a_tags:
                href = a.attr('href')
                if href:
                    match = re.search(r'/student/course/(\d+)', href)
                    if match:
                        class_set.add(match.group(1))

            # 等待监听到目标请求，从中提取 Cookie
            console.print("  [cyan]▶[/cyan] 等待自动捕获 Cookie…")
            packet = page.listen.wait(timeout=30)

            if packet:
                cookie_str = packet.request.headers.get('Cookie', '')
                pattern = rf'{COOKIE_KEY}=[^;]+'
                result = re.search(pattern, cookie_str)
                if result:
                    extracted = result.group(0)
                    # 避免重复添加同一个 Cookie
                    if extracted not in cookie_list:
                        cookie_list.append(extracted)
                        console.print(f"  [bold green]✔[/bold green] Cookie 已捕获：[dim]{extracted[:40]}…[/dim]")
                    else:
                        console.print("  [yellow]ℹ[/yellow]  该 Cookie 已存在，跳过。")
                else:
                    console.print("  [bold red]✗[/bold red] 未在请求中找到目标 Cookie，请检查账号是否正确。")
            else:
                console.print("  [bold red]✗[/bold red] 监听超时，未能捕获 Cookie。")

        finally:
            # 无论成功与否，都停止监听并关闭浏览器
            page.listen.stop()
            page.close()

        console.print(
            f"  [dim]当前已收集账号数：[bold]{len(cookie_list)}[/bold]，班级数：[bold]{len(class_set)}[/bold][/dim]"
        )

    class_list = sorted(class_set)

    # 允许用户手动额外输入班级 ID（应对页面课程未显示的情况）
    console.print(f"\n  自动检测到的班级 ID：[bold cyan]{class_list if class_list else '（无）'}[/bold cyan]")
    while True:
        manual = prompt_input("  手动添加班级 ID（留空结束）：").strip()
        if not manual:
            break
        if manual not in class_list:
            class_list.append(manual)
            console.print(f"  [bold green]✔[/bold green] 已添加班级 ID：[cyan]{manual}[/cyan]")

    return class_list, cookie_list


# ──────────────────────────────────────────────
#  步骤 2：配置签到定位点
# ──────────────────────────────────────────────

def configure_locations(existing_locations: list) -> list:
    """
    引导用户配置签到使用的经纬度定位点列表。
    会打开腾讯坐标拾取工具网页供用户参考，然后在终端手动输入坐标。

    参数：
        existing_locations — 已有的定位点列表（用于追加）

    返回：
        更新后的定位点列表，每个元素为 {"lat": str, "lng": str, "acc": str}
    """
    locations = list(existing_locations)

    print_step_header(
        2, 4,
        "配置签到定位点",
        "程序将打开腾讯坐标拾取工具，点击地图获取经纬度后在此处输入。支持多个定位点。"
    )

    if not questionary.confirm("是否现在配置定位点？", default=True).ask():
        console.print("  [yellow]跳过定位配置，将使用已有定位点。[/yellow]")
        return locations

    # 打开腾讯地图坐标拾取工具
    map_page = ChromiumPage()
    try:
        console.print("  [cyan]▶[/cyan] 正在打开腾讯坐标拾取工具，请在地图上点击目标位置…")
        map_page.get(MAP_URL)
        console.print(
            Panel(
                "[bold]使用方法[/bold]\n"
                "1. 在打开的浏览器地图中，[yellow]点击签到地点[/yellow]\n"
                "2. 页面会显示该点的 [cyan]纬度(lat)[/cyan] 和 [cyan]经度(lng)[/cyan]\n"
                "3. 将数值复制后在此处输入\n"
                "4. 完成所有定位点输入后程序会自动关闭地图",
                border_style="blue",
                padding=(0, 2),
            )
        )

        while True:
            idx = len(locations) + 1
            add_more = questionary.confirm(
                f"添加第 {idx} 个定位点？",
                default=True
            ).ask()
            if not add_more:
                break

            console.print(
                f"\n  [bold]定位点 #{idx}[/bold]  "
                "[dim]经纬度尽量输入 8 位小数（不足八位时脚本自动随机补全），用于签到时的微偏移！[/dim]"
            )

            lat = ""
            while not lat:
                lat = prompt_input("  请输入纬度 (lat)：").strip()
                if not re.match(r'^\d+\.\d{4,}$', lat):
                    console.print("  [bold red]✗[/bold red] 格式不正确，例如：39.90123456（至少4位小数）")
                    lat = ""

            lng = ""
            while not lng:
                lng = prompt_input("  请输入经度 (lng)：").strip()
                if not re.match(r'^\d+\.\d{4,}$', lng):
                    console.print("  [bold red]✗[/bold red] 格式不正确，例如：116.40123456（至少4位小数）")
                    lng = ""

            acc = prompt_input("  请输入海拔 (acc)，不确定可直接回车使用默认值 10：", default="10")

            locations.append({"lat": lat, "lng": lng, "acc": acc})
            console.print(
                f"  [bold green]✔[/bold green] 已添加定位点 #{idx}："
                f"[cyan]纬度={lat}[/cyan]  [cyan]经度={lng}[/cyan]  [dim]海拔={acc}[/dim]"
            )

    finally:
        # 输入完成后关闭地图浏览器
        console.print("\n  [cyan]▶[/cyan] 定位配置完成，关闭地图窗口…")
        map_page.close()

    return locations


# ──────────────────────────────────────────────
#  步骤 3：配置定时签到时间
# ──────────────────────────────────────────────

def configure_schedule_times(existing_times: list) -> list:
    """
    引导用户配置定时签到时间点列表。
    支持添加多个时间点，main.py 会为每个时间点注册一个 schedule 任务。

    参数：
        existing_times — 已有的时间点列表（字符串列表，格式 "HH:MM"）

    返回：
        更新后的时间点列表
    """
    times = list(existing_times)

    print_step_header(
        3, 4,
        "配置定时签到时间",
        "支持设置多个时间点，main.py 将在每个时间点自动触发签到。格式：HH:MM（如 08:05）"
    )

    while True:
        idx = len(times) + 1
        add = questionary.confirm(
            f"添加第 {idx} 个定时时间点？（不设则为立即签到模式）",
            default=(len(times) == 0)   # 第一个时间点默认回答是，之后默认否
        ).ask()
        if not add:
            break

        time_str = ""
        while not time_str:
            time_str = prompt_input("  请输入签到时间（格式 HH:MM，例如 08:05）：").strip()
            if not re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', time_str):
                console.print("  [bold red]✗[/bold red] 格式错误！例如：08:05、12:30、18:00")
                time_str = ""

        if time_str not in times:
            times.append(time_str)
            console.print(f"  [bold green]✔[/bold green] 已添加时间点：[bold cyan]{time_str}[/bold cyan]")
        else:
            console.print(f"  [yellow]ℹ[/yellow]  时间点 {time_str} 已存在，跳过。")

    if times:
        console.print(f"\n  已配置的定时时间点：[bold cyan]{times}[/bold cyan]")
    else:
        console.print("\n  [yellow]未配置定时时间点，main.py 启动后将立即执行一次签到。[/yellow]")

    return times


# ──────────────────────────────────────────────
#  步骤 4：配置 PushPlus 推送
# ──────────────────────────────────────────────

def configure_pushplus(existing_token: str) -> str:
    """
    引导用户配置 PushPlus 消息推送 Token（可选）。

    参数：
        existing_token — 已有的 Token 字符串（可能为空）

    返回：
        用户输入的 Token 字符串，留空则返回空字符串。
    """
    print_step_header(
        4, 4,
        "配置 PushPlus 推送（可选）",
        "签到成功后可通过 PushPlus 推送微信消息通知。Token 获取：http://www.pushplus.plus/"
    )
    console.print("  [dim]注意：多人签到场景下推送功能可能不完整。[/dim]\n")

    if existing_token:
        console.print(f"  当前已有 Token：[dim]{existing_token[:10]}…[/dim]")
        if not questionary.confirm("  是否修改 PushPlus Token？", default=False).ask():
            return existing_token

    token = prompt_input("  请输入 PushPlus Token（留空不使用推送）：")
    if token:
        console.print(f"  [bold green]✔[/bold green] 已设置 PushPlus Token：[dim]{token[:10]}…[/dim]")
    else:
        console.print("  [yellow]ℹ[/yellow]  未配置推送，跳过。")
    return token


# ──────────────────────────────────────────────
#  配置汇总展示
# ──────────────────────────────────────────────

def print_summary(config: dict):
    """
    以 Rich 表格形式展示最终配置汇总。

    参数：
        config — 完整的配置字典
    """
    console.print()
    console.rule("[bold yellow]配置汇总[/bold yellow]")

    table = Table(box=box.ROUNDED, border_style="dim", show_header=False, padding=(0, 1))
    table.add_column("项目", style="bold cyan", no_wrap=True)
    table.add_column("值", style="white")

    table.add_row("班级 ID", ", ".join(config["classes"]) if config["classes"] else "[red]未配置[/red]")
    table.add_row("定位点数", f"{len(config['locations'])} 个")
    table.add_row("账号数", f"{len(config['cookies'])} 个")

    if config["scheduletimes"]:
        table.add_row("定时时间", "[cyan]" + "  /  ".join(config["scheduletimes"]) + "[/cyan]")
    else:
        table.add_row("定时时间", "[yellow]未设置（立即签到模式）[/yellow]")

    table.add_row("PushPlus 推送", "[green]已配置[/green]" if config["pushplus"] else "[dim]未配置[/dim]")
    table.add_row("调试模式", "[yellow]开启[/yellow]" if config["debug"] else "[dim]关闭[/dim]")

    console.print(table)
    console.print()


# ──────────────────────────────────────────────
#  主流程
# ──────────────────────────────────────────────

def main():
    """
    配置向导主流程：
    1. 打印横幅
    2. 读取已有配置（支持追加/覆盖）
    3. 依次执行四个配置步骤
    4. 展示汇总并写入 config.json
    """
    print_banner()

    # 读取已有配置，允许用户在已有基础上修改
    existing = load_existing_config()
    if existing:
        console.print(
            Panel(
                "[yellow]检测到已有配置文件，本次配置将在原有基础上修改。[/yellow]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        if questionary.confirm("是否清空现有配置？", default=False).ask():
            existing = {}
            console.print(
                Panel(
                    "[red]现有配置已清空，即将开始重新配置所有项。[/red]",
                    border_style="red",
                    padding=(0, 2),
                )
            )
    else:
        console.print("[dim]未检测到配置文件，将创建新配置。[/dim]\n")

    # 取出已有值，传给各配置步骤，支持追加不破坏原有数据y
    existing_classes   = existing.get("classes", [])
    existing_locations = existing.get("locations", [])
    existing_cookies   = existing.get("cookies", [])
    existing_times     = existing.get("scheduletimes", [])
    existing_pushplus  = existing.get("pushplus", "")
    existing_debug     = existing.get("debug", False)

    console.print()

    # ── 步骤 1：登录获取班级 ID 与 Cookie ──
    class_list, cookie_list = login_and_capture(existing_cookies)

    # 合并已有班级 ID（去重）
    for cid in existing_classes:
        if cid not in class_list:
            class_list.append(cid)

    console.print()

    # ── 步骤 2：配置定位点 ──
    locations = configure_locations(existing_locations)

    console.print()

    # ── 步骤 3：配置定时时间 ──
    schedule_times = configure_schedule_times(existing_times)

    console.print()

    # ── 步骤 4：配置 PushPlus ──
    pushplus_token = configure_pushplus(existing_pushplus)

    console.print()

    # ── 调试模式 ──
    console.rule("[dim]其他设置[/dim]")
    debug = questionary.confirm(
        "是否启用调试模式（Debug）？启用后会将详细日志写入 AutoCheckBJMF.log",
        default=existing_debug
    ).ask()

    # ── 汇总配置 ──
    config = {
        "classes":       class_list,     # 班级 ID 列表
        "locations":     locations,       # 签到定位点列表
        "cookies":       cookie_list,     # Cookie 列表
        "scheduletimes": schedule_times,  # 定时时间列表
        "pushplus":      pushplus_token,  # PushPlus Token
        "debug":         debug            # 调试模式
    }

    # 展示配置汇总
    print_summary(config)

    if questionary.confirm("确认保存以上配置？", default=True).ask():
        save_config(config)
        console.print(
            Panel(
                "[bold green]🎉 配置完成！[/bold green]\n\n"
                "  [cyan]python main.py[/cyan]   → 启动定时自动签到\n"
                "  [cyan]python once.py[/cyan]   → 立即执行一次签到（应急使用）",
                border_style="green",
                padding=(1, 4),
            )
        )
    else:
        console.print("[yellow]已取消，配置未保存。[/yellow]")


if __name__ == "__main__":
    main()
