"""
make_config.py — AutoCheckBJMF 配置向导
=========================================
交互式终端引导用户完成所有配置，并将结果写入 config.json。

配置格式：
{
    "classes":      ["123456", "789012"],        # 班级 ID 列表（支持多班级）
    "locations": [                               # 签到定位点列表（支持多个）
        {"lat": "39.90000000", "lng": "116.40000000", "acc": "10"}
    ],
    "cookies":      ["remember_student_xxx=..."], # 用户 Cookie 列表（支持多账号）
    "schedule_windows": [                        # 每日签到区间（支持多个）
        {"start": "08:00", "end": "08:30", "interval_seconds": 300}
    ],
    "pushplus":     "",                           # PushPlus 推送 Token（可选）
    "feishu_webhook": "",                         # 飞书自定义机器人 Webhook（可选）
    "debug":        false                         # 调试模式
}
"""

import re
import questionary
from DrissionPage import ChromiumPage

from core.config_wizard import (
    load_existing_config,
    print_config_banner,
    print_step_header,
    prompt_input,
    save_config,
)
from core.constants import COOKIE_KEY
from core.location import is_valid_coordinate, parse_coordinate_pair
from core.prompts import confirm_or_default
from core.scheduler import (
    format_schedule_window,
    normalize_schedule_time,
    schedule_descriptions,
    validate_schedule_config,
)
from core.ui import console

# ── Rich 终端美化库 ──
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.rule import Rule

# ──────────────────────────────────────────────
#  常量定义
# ──────────────────────────────────────────────

# 微信扫码登录地址
LOGIN_URL = "https://bj.k8n.cn/login/qr/weixin/student/2"

# 扫码后等待跳转的监听目标
LISTEN_TARGET = "https://bj.k8n.cn/student"

# 腾讯坐标拾取工具地址
MAP_URL = "https://lbs.qq.com/getPoint/"


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
                "[dim]可直接粘贴地图坐标，格式如 22.766885,108.451339。[/dim]"
            )

            lat = ""
            lng = ""
            while not lat or not lng:
                coord_text = prompt_input(
                    "  请输入经纬度（纬度,经度；直接回车则分开输入）：",
                    placeholder="22.766885,108.451339"
                ).strip()

                if coord_text:
                    parsed = parse_coordinate_pair(coord_text)
                    if parsed:
                        lat, lng = parsed
                        break
                    console.print("  [bold red]✗[/bold red] 格式不正确，例如：22.766885,108.451339")
                    continue

                lat = prompt_input("  请输入纬度 (lat)：").strip()
                if not is_valid_coordinate(lat, -90, 90):
                    console.print("  [bold red]✗[/bold red] 纬度格式不正确，例如：22.766885（至少4位小数）")
                    lat = ""
                    continue

                lng = prompt_input("  请输入经度 (lng)：").strip()
                if not is_valid_coordinate(lng, -180, 180):
                    console.print("  [bold red]✗[/bold red] 经度格式不正确，例如：108.451339（至少4位小数）")
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

def prompt_schedule_window(existing: dict | None = None) -> dict:
    """输入一个区间，修改时留空保留原值。"""
    existing = existing or {}
    while True:
        values = {}
        for key, label in (("start", "开始时间"), ("end", "结束时间")):
            default = existing.get(key, "")
            while True:
                raw = prompt_input(
                    f"  {label}（HH:MM）" + (f" [{default}]" if default else "") + "：",
                    default=default,
                )
                value = normalize_schedule_time(raw)
                if value:
                    values[key] = value
                    break
                console.print("  [red]时间格式错误，例如 08:05、8：00。[/red]")
        default_interval = str(existing.get("interval_seconds", 300))
        while True:
            raw = prompt_input(f"  执行步长（秒）[{default_interval}]：", default=default_interval)
            try:
                interval = int(raw)
                if interval > 0:
                    break
            except ValueError:
                pass
            console.print("  [red]步长必须是正整数秒。[/red]")
        values["interval_seconds"] = interval
        try:
            validate_schedule_config({"schedule_windows": [values]})
            return values
        except ValueError as e:
            console.print(f"  [red]{e}，请重新输入。[/red]")


def configure_schedule(existing: dict) -> dict:
    """管理多个区间；旧配置可原样保留，也可切换到区间模式。"""
    print_step_header(
        3, 4, "配置签到时间区间",
        "时间统一为北京时间（UTC+8）；包含开始、不包含结束，结束早于开始表示跨午夜。",
    )
    if "schedule_windows" not in existing and existing.get("scheduletimes"):
        console.print("  当前旧时间点配置：" + "、".join(existing["scheduletimes"]))
        if not confirm_or_default("切换为时间区间模式？（选择否则保留旧时间点）", default=True):
            return {"scheduletimes": list(existing["scheduletimes"])}

    windows = [dict(window) for window in existing.get("schedule_windows", [])]
    while True:
        console.print()
        for index, window in enumerate(windows, 1):
            console.print(f"  {index}. {format_schedule_window(window)}")
        if not windows:
            console.print("  [yellow]尚无区间；保存空列表将使用立即执行一次模式。[/yellow]")
        choices = ["添加区间"]
        if windows:
            choices += ["修改区间", "删除区间"]
        choices += ["完成配置"]
        action = questionary.select("选择操作：", choices=choices).ask()
        if action is None:
            raise KeyboardInterrupt
        if action == "完成配置":
            return {"schedule_windows": windows}
        if action == "添加区间":
            window = prompt_schedule_window()
            if window not in windows:
                windows.append(window)
            else:
                console.print("  [yellow]相同区间已存在，跳过。[/yellow]")
        else:
            selected = questionary.select(
                "选择区间：",
                choices=[questionary.Choice(f"{i + 1}. {format_schedule_window(w)}", value=i)
                         for i, w in enumerate(windows)],
            ).ask()
            if selected is None:
                continue
            if action == "删除区间":
                windows.pop(selected)
            else:
                window = prompt_schedule_window(windows[selected])
                if any(w == window for i, w in enumerate(windows) if i != selected):
                    console.print("  [yellow]相同区间已存在，保留原配置。[/yellow]")
                else:
                    windows[selected] = window


# ──────────────────────────────────────────────
#  步骤 4：配置消息推送
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
        "配置消息推送（可选）",
        "签到成功后可通过 PushPlus 或飞书自定义机器人 Webhook 发送通知。"
    )
    console.print("  [bold]PushPlus[/bold]  [dim]Token 获取：http://www.pushplus.plus/[/dim]\n")

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


def configure_feishu_webhook(existing_webhook: str) -> str:
    """
    引导用户配置飞书自定义机器人 Webhook（可选）。

    参数：
        existing_webhook — 已有的 Webhook URL 字符串（可能为空）

    返回：
        用户输入的 Webhook URL 字符串，留空则返回空字符串。
    """
    console.print("\n  [bold]飞书自定义机器人 Webhook[/bold]")
    console.print("  [dim]格式示例：https://open.feishu.cn/open-apis/bot/v2/hook/xxxx[/dim]\n")

    if existing_webhook:
        masked = existing_webhook[:40] + "…" if len(existing_webhook) > 40 else existing_webhook
        console.print(f"  当前已有飞书 Webhook：[dim]{masked}[/dim]")
        if not questionary.confirm("  是否修改飞书 Webhook？", default=False).ask():
            return existing_webhook

    webhook = prompt_input("  请输入飞书 Webhook URL（留空不使用飞书推送）：")
    if webhook:
        console.print("  [bold green]✔[/bold green] 已设置飞书 Webhook")
    else:
        console.print("  [yellow]ℹ[/yellow]  未配置飞书推送，跳过。")
    return webhook


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

    descriptions = schedule_descriptions(config)
    if descriptions:
        table.add_row("签到计划", "[cyan]" + "\n".join(descriptions) + "[/cyan]")
    else:
        table.add_row("定时时间", "[yellow]未设置（立即签到模式）[/yellow]")

    table.add_row("PushPlus 推送", "[green]已配置[/green]" if config["pushplus"] else "[dim]未配置[/dim]")
    table.add_row("飞书推送", "[green]已配置[/green]" if config["feishu_webhook"] else "[dim]未配置[/dim]")
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
    print_config_banner()

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
    existing_pushplus  = existing.get("pushplus", "")
    existing_feishu    = existing.get("feishu_webhook", existing.get("feishu_websocket", ""))
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
    schedule_config = configure_schedule(existing)

    console.print()

    # ── 步骤 4：配置消息推送 ──
    pushplus_token = configure_pushplus(existing_pushplus)
    feishu_webhook = configure_feishu_webhook(existing_feishu)

    console.print()

    # ── 调试模式 ──
    console.rule("[dim]其他设置[/dim]")
    debug = confirm_or_default(
        "是否启用调试模式（Debug）？启用后会将详细日志写入 AutoCheckBJMF.log",
        default=existing_debug
    )

    # ── 汇总配置 ──
    config = {
        "classes":       class_list,     # 班级 ID 列表
        "locations":     locations,       # 签到定位点列表
        "cookies":       cookie_list,     # Cookie 列表
        **schedule_config,              # 区间配置或兼容旧时间点
        "pushplus":      pushplus_token,  # PushPlus Token
        "feishu_webhook": feishu_webhook,  # 飞书自定义机器人 Webhook
        "debug":         debug            # 调试模式
    }

    # 展示配置汇总
    print_summary(config)

    if confirm_or_default("确认保存以上配置？", default=True):
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
