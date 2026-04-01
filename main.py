"""
main.py — AutoCheckBJMF 定时签到主程序
==========================================
读取 config.json 中的配置，为每个 scheduletimes 时间点注册定时任务，
在指定时间自动对所有班级、所有账号执行签到。

使用方式：
    python main.py

若 config.json 不存在，请先运行 make_config.py 生成配置。
"""

import random
import requests
import re
import time
import os
import json
import logging
import schedule
from datetime import datetime
from bs4 import BeautifulSoup

# ── Rich 终端美化库 ──
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.rule import Rule

# 全局 Rich 控制台实例
console = Console()

# ──────────────────────────────────────────────
#  配置加载
# ──────────────────────────────────────────────

# 配置文件路径（与脚本同目录）
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# PushPlus 推送地址模板
PUSHPLUS_URL = "http://www.pushplus.plus/send?token={token}&title={title}&content={content}"

# Cookie 中需要提取的字段名
COOKIE_KEY = "remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d"
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
    console.print()

def load_config() -> dict:
    """
    加载并校验 config.json 配置文件。

    返回：
        配置字典，包含 classes / locations / cookies / scheduletimes / pushplus / debug

    异常：
        若文件不存在或格式错误，打印提示并退出程序。
    """
    if not os.path.exists(CONFIG_PATH):
        console.print(Panel(
            "[bold red]❌ 未找到 config.json[/bold red]\n"
            "请先运行 [cyan]python make_config.py[/cyan] 生成配置文件。",
            border_style="red", padding=(0, 2)
        ))
        input("按回车退出…")
        raise SystemExit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"[bold red]❌ config.json 格式错误：[/bold red]{e}")
            input("按回车退出…")
            raise SystemExit(1)

    # 基础校验
    required_keys = ["classes", "locations", "cookies", "scheduletimes"]
    for key in required_keys:
        if key not in cfg:
            console.print(f"[bold red]❌ config.json 缺少必要字段：[/bold red][cyan]{key}[/cyan]，请重新运行 make_config.py")
            input("按回车退出…")
            raise SystemExit(1)

    return cfg


# ──────────────────────────────────────────────
#  日志初始化
# ──────────────────────────────────────────────

def setup_logger(debug: bool) -> logging.Logger:
    """
    初始化日志记录器。
    调试模式下将 INFO 及以上级别的日志写入 AutoCheckBJMF.log（UTF-8 编码）。

    参数：
        debug — 是否启用调试模式

    返回：
        logging.Logger 实例
    """
    logger = logging.getLogger("AutoCheckBJMF")
    if debug:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler("AutoCheckBJMF.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.info("调试模式已启用")
    return logger


# ──────────────────────────────────────────────
#  核心签到逻辑
# ──────────────────────────────────────────────

def modify_decimal_part(num: float | str) -> float:
    """
    对经纬度小数部分的第 4~8 位施加随机偏移，实现签到定位微偏移。
    多人签到时每人坐标略有不同，避免被系统识别为异常。

    参数：
        num — 原始经度或纬度值（支持浮点数或字符串格式）

    返回：
        偏移后的经纬度浮点值
    """
    num = float(num)
    # 确保至少有 8 位小数
    num_str = f"{num:.8f}"
    decimal_index = num_str.find('.')
    # 提取小数点后第 4~8 位（5 个数字）
    decimal_part = num_str[decimal_index + 4: decimal_index + 9]
    decimal_value = int(decimal_part)
    # 随机偏移 ±15000（对应小数第 4~8 位的微小变动）
    random_offset = random.randint(-15000, 15000)
    new_decimal_value = abs(decimal_value + random_offset)
    new_decimal_str = f"{new_decimal_value:05d}"
    # 拼接回完整坐标字符串
    new_num_str = num_str[:decimal_index + 4] + new_decimal_str + num_str[decimal_index + 9:]
    return float(new_num_str)


def pick_location(locations: list) -> dict:
    """
    从定位点列表中随机选取一个定位点。

    参数：
        locations — 定位点字典列表，每项包含 lat / lng / acc

    返回：
        随机选中的定位点字典
    """
    return random.choice(locations)


def qiandao(
    class_id: str,
    cookies: list,
    locations: list,
    pushplus_token: str,
    debug: bool,
    logger: logging.Logger
) -> tuple[list, int]:
    """
    对单个班级执行所有账号的签到，包含重试和倒数动画。

    参数：
        class_id      — 班级 ID 字符串
        cookies       — 用户 Cookie 字符串列表（提取后的格式）
        locations     — 定位点字典列表（随机选取）
        pushplus_token — PushPlus Token（为空则不推送）
        debug         — 是否为调试模式
        logger        — 日志记录器

    返回：
        (error_cookies, null_count)
            error_cookies — 本次签到失败的 Cookie 列表（用于重试）
            null_count    — Cookie 格式无效的数量
    """
    url = f"http://k8n.cn/student/course/{class_id}/punchs"
    error_cookies = []
    null_count = 0

    for uid, raw_cookie in enumerate(cookies):
        # ── 提取用户备注（格式：username=<备注>;remember...） ──
        username_match = re.search(r'username=[^;]+', raw_cookie)
        username_tag = f" <{username_match.group(0).split('=')[1]}>" if username_match else ""

        time.sleep(random.randint(1, 3))
        console.print(
            f"\r  [bold yellow]★{uid+1}★[/bold yellow] {username_tag} [bold yellow]开始签到 ★{uid+1}★[/bold yellow]"
        )

        # ── 提取有效的 Cookie 字段 ──
        cookie_match = re.search(rf'{COOKIE_KEY}=[^;]+', raw_cookie)
        if not cookie_match:
            null_count += 1
            console.print(f"  [bold red]✗[/bold red] 未找到有效 Cookie，请检查账号 {uid+1} 的 Cookie 配置！")
            continue

        extracted_cookie = cookie_match.group(0)
        if debug:
            console.print(f"  [dim][Debug] Cookie: {extracted_cookie}[/dim]")

        # ── 构造请求头 ──
        headers = {
            'User-Agent':      ('Mozilla/5.0 (Linux; Android 9; AKT-AK47 Build/USER-AK47; wv) '
                                'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 '
                                'Mobile Safari/537.36 XWEB/1160065 MMWEBSDK/20231202 MMWEBID/1136 '
                                'MicroMessenger/8.0.47.2560(0x28002F35) WeChat/arm64 Weixin '
                                'NetType/4G Language/zh_CN ABI/arm64'),
            'Accept':          ('text/html,application/xhtml+xml,application/xml;q=0.9,'
                                'image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;'
                                'q=0.8,application/signed-exchange;v=b3;q=0.7'),
            'X-Requested-With': 'com.tencent.mm',
            'Referer':         f'http://k8n.cn/student/course/{class_id}',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh-SG;q=0.9,zh;q=0.8,en-SG;q=0.7,en-US;q=0.6,en;q=0.5',
            'Cookie':          extracted_cookie
        }

        # ── 获取签到任务列表 ──
        try:
            response = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            console.print(f"  [bold red]✗[/bold red] 网络请求失败：{e}")
            error_cookies.append(raw_cookie)
            continue

        console.print(f"  [cyan]▶[/cyan] 班级 [bold]{class_id}[/bold] 课程页面响应：[dim]{response.status_code}[/dim]")

        soup = BeautifulSoup(response.text, 'html.parser')
        all_matches = []
        title_tag = soup.find('title')
        # 若页面出现"出错"字样，视为登录状态异常
        if not title_tag or "出错" in title_tag.text:
            console.print(f"  [bold red]✗[/bold red] 登录状态异常（账号 {uid+1}），加入重试队列")
            logger.error(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 登录状态异常")
            error_cookies.append(raw_cookie)
            continue

        # 匹配元素
        """
        <a id="gps_btn_4984548" href="/student/punchw/course/136341/4984548?sid=2715917" class="gps_btn_a btn btn-light btn-sm btn-block">
                                                        点此去完成签到
                                                    </a>
        """
        gps_btn = soup.find('a', id=re.compile(r'^gps_btn_\d+$'))
        if gps_btn:
            gps_id = re.compile(r'\d+').search(gps_btn.get('id')).group(0)
            all_matches.append(gps_id)
            
        # ── 提取扫码签到 ID ──
        # scan_matches = re.compile(r'punchcard_(\d+)').findall(response.text)
        # all_matches = gps_matches + scan_matches
        # todo 先不考虑扫码签到，后续再完善

        console.print(f"  [cyan]▶[/cyan] 找到 GPS 签到 ID：[bold cyan]{all_matches}[/bold cyan]")

        if not all_matches:
            console.print(f"  [yellow]ℹ[/yellow]  班级 [bold]{class_id}[/bold] 暂无进行中的签到任务。")
            continue

        # ── 对每个签到 ID 发起签到请求 ──
        for match_id in all_matches:
            for loc in locations:
                new_lat = modify_decimal_part(loc["lat"])
                new_lng = modify_decimal_part(loc["lng"])
                acc = loc["acc"]

                sign_url = f"http://k8n.cn/student/punchs/course/{class_id}/{match_id}"
                payload = {
                    'id':       match_id,
                    'lat':      new_lat,
                    'lng':      new_lng,
                    'acc':      acc,
                    'res':      '',    # 拍照签到字段（留空）
                    'gps_addr': ''     # 地址描述（留空）
                }

                try:
                    sign_resp = requests.post(sign_url, headers=headers, data=payload, timeout=15)
                except requests.RequestException as e:
                    console.print(f"  [bold red]✗[/bold red] 签到请求失败：{e}")
                    error_cookies.append(raw_cookie)
                    continue

                console.print(
                    f"  [cyan]▶[/cyan] 签到请求已发送："
                    f"ID[[bold]{match_id}[/bold]] "
                    f"坐标[[cyan]{new_lat:.6f}, {new_lng:.6f}[/cyan]] "
                    f"海拔[[dim]{acc}[/dim]]"
                )
                logger.info(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 签到ID[{match_id}] | 坐标[{new_lat},{new_lng}]")

                if sign_resp.status_code == 200:
                    result_soup = BeautifulSoup(sign_resp.text, 'html.parser')
                    div_tag = result_soup.find('div', id='title')
                    if div_tag:
                        result_text = div_tag.text.strip()
                        # 根据结果文字选择颜色
                        if result_text == "签到成功":
                            console.print(f"  [bold green]✔[/bold green] 签到结果：[bold green]{result_text}[/bold green]")
                            break
                        else:
                            console.print(f"  [yellow]⚠[/yellow] 签到结果：[yellow]{result_text}[/yellow]")
                            continue
                        logger.info(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 签到结果：{result_text}")
                        # 签到成功时发送 PushPlus 通知
                        if pushplus_token and result_text == "签到成功":
                            try:
                                notify_url = PUSHPLUS_URL.format(
                                    token=pushplus_token,
                                    title="班级魔方自动签到",
                                    content=f"用户{uid+1}{username_tag} 班级{class_id} {result_text}"
                                )
                                requests.get(notify_url, timeout=10)
                            except Exception:
                                console.print("  [yellow]⚠[/yellow] PushPlus 推送失败，但签到可能已成功")
                    else:
                        console.print(f"  [yellow]⚠[/yellow] 未找到签到结果标签，可能签到成功但响应格式变化")
                        logger.warning(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 未找到结果标签")
                else:
                    console.print(f"  [bold red]✗[/bold red] 签到请求失败，状态码：[red]{sign_resp.status_code}[/red]，加入重试队列")
                    logger.error(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 请求失败 {sign_resp.status_code}")
                    error_cookies.append(raw_cookie)

    return error_cookies, null_count


def run_all_classes(
    classes: list,
    cookies: list,
    locations: list,
    pushplus_token: str,
    debug: bool,
    logger: logging.Logger
):
    """
    遍历所有班级，依次执行签到，并对失败的 Cookie 重试最多两次。

    参数：
        classes        — 班级 ID 列表
        cookies        — Cookie 字符串列表
        locations      — 定位点列表
        pushplus_token — PushPlus Token
        debug          — 调试模式
        logger         — 日志记录器
    """
    console.rule(f"[bold cyan]开始签到  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/bold cyan]")
    console.print(
        f"  班级数：[bold]{len(classes)}[/bold]  账号数：[bold]{len(cookies)}[/bold]  "
        f"定位点数：[bold]{len(locations)}[/bold]"
    )

    for class_id in classes:
        console.print(f"\n  [cyan]▶[/cyan] 开始签到班级：[bold cyan]{class_id}[/bold cyan]")
        error_cookies, null_count = qiandao(
            class_id, cookies, locations, pushplus_token, debug, logger
        )

        # ── 第一次重试（30后） ──
        if error_cookies:
            console.print(f"\n  [yellow]⚠[/yellow] 有 [bold]{len(error_cookies)}[/bold] 个账号签到失败，5 分钟后重试…")
            time.sleep(30)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger
            )

        # ── 第二次重试（再等 5 分钟） ──
        if error_cookies:
            console.print(f"\n  [yellow]⚠[/yellow] 仍有 [bold]{len(error_cookies)}[/bold] 个账号失败，15 分钟后最后一次重试…")
            time.sleep(300)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger
            )

        if error_cookies:
            console.print(Panel(
                f"[bold red]❌ 班级 {class_id}：仍有账号签到失败[/bold red]\n"
                "请检查 Cookie 是否过期或网络是否正常。",
                border_style="red", padding=(0, 2)
            ))
        elif null_count > 0:
            console.print(f"\n  [yellow]⚠[/yellow] 班级 [bold]{class_id}[/bold]：存在 {null_count} 个无效 Cookie，请检查配置。")
        else:
            console.print(Panel(
                f"[bold green]✅ 班级 {class_id}：本次签到圆满成功！[/bold green]",
                border_style="green", padding=(0, 2)
            ))

    console.rule("[dim]签到结束[/dim]")


# ──────────────────────────────────────────────
#  倒计时显示
# ──────────────────────────────────────────────

def show_countdown(schedule_times: list):
    """
    在终端实时显示距离最近一次定时任务的剩余时间。
    剩余 < 5 分钟时每秒刷新，否则每分钟刷新一次。

    参数：
        schedule_times — 定时时间字符串列表，格式 "HH:MM"
    """
    import time as _time

    now = _time.time()
    # 计算所有时间点的下次触发时间戳，取最近的一个
    next_stamps = []
    for t_str in schedule_times:
        hour, minute = map(int, t_str.split(":"))
        today = _time.strftime("%Y-%m-%d", _time.localtime(now))
        target_struct = _time.strptime(f"{today} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
        stamp = _time.mktime(target_struct)
        if stamp < now:
            stamp += 24 * 3600   # 今天已过，改为明天
        next_stamps.append((stamp, t_str))

    # 找到最近的时间点
    next_stamp, next_time_str = min(next_stamps, key=lambda x: x[0])
    remaining = int(next_stamp - now)

    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    current = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(now))

    if remaining < 300:
        # 5 分钟内：显示分秒，每秒刷新
        # 使用 \r 覆盖同一行（rich end="" 同样支持）
        console.print(
            f"\r⏰  当前 [dim]{current}[/dim]  │  "
            f"下次任务 [bold cyan]{next_time_str}[/bold cyan]  │  "
            f"剩余 [bold yellow]{minutes}[/bold yellow] 分 [bold yellow]{seconds}[/bold yellow] 秒   ",
            end=""
        )
        _time.sleep(1)
    else:
        # 5 分钟以上：显示时分，每分钟刷新
        console.print(
            f"\r⏰  当前 [dim]{current}[/dim]  │  "
            f"下次任务 [bold cyan]{next_time_str}[/bold cyan]  │  "
            f"剩余 [bold yellow]{hours}[/bold yellow] 小时 [bold yellow]{minutes}[/bold yellow] 分钟   ",
            end=""
        )
        _time.sleep(60)


# ──────────────────────────────────────────────
#  主程序入口
# ──────────────────────────────────────────────

def main():
    """
    main.py 程序入口：
    1. 加载配置文件
    2. 初始化日志
    3. 若有定时时间则注册 schedule 任务并循环倒计时
    4. 若无定时时间则立即执行一次签到后退出
    """
    print_banner()
    console.print(Panel(
        "[bold white]AutoCheckBJMF — 班级魔方自动签到[/bold white]  [dim]定时模式[/dim]\n"
        "[dim]项目地址：https://github.com/Moeus/AutoCheckBJMF[/dim]",
        border_style="cyan", padding=(0, 4)
    ))

    # 加载配置
    cfg = load_config()
    classes        = cfg["classes"]
    locations      = cfg["locations"]
    cookies        = cfg["cookies"]
    schedule_times = cfg["scheduletimes"]
    pushplus_token = cfg.get("pushplus", "")
    debug          = cfg.get("debug", False)

    # 初始化日志系统
    logger = setup_logger(debug)

    # 打印当前配置摘要（Rich Table）
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("项目", style="bold cyan", no_wrap=True)
    table.add_column("值", style="white")
    table.add_row("班级 ID", ", ".join(classes) if classes else "[red]未配置[/red]")
    table.add_row("账号数", str(len(cookies)))
    table.add_row("定位点数", str(len(locations)))
    if schedule_times:
        table.add_row("定时时间", "[cyan]" + "  /  ".join(schedule_times) + "[/cyan]")
    else:
        table.add_row("定时时间", "[yellow]未设置（立即执行）[/yellow]")
    table.add_row("PushPlus", "[green]已配置[/green]" if pushplus_token else "[dim]未配置[/dim]")
    table.add_row("调试模式", "[yellow]开启[/yellow]" if debug else "[dim]关闭[/dim]")
    console.print(table)

    # 封装签到任务为 schedule 回调
    def job():
        run_all_classes(classes, cookies, locations, pushplus_token, debug, logger)
        if schedule_times:
            console.print("\n  [dim]☆ 本次签到结束，继续等待下一个定时任务…[/dim]\n")

    if schedule_times:
        # ── 定时模式：为每个时间点注册 schedule 任务 ──
        for t_str in schedule_times:
            schedule.every().day.at(t_str).do(job)
            console.print(f"  [bold green]✔[/bold green] 已注册定时任务：每天 [bold cyan]{t_str}[/bold cyan]")

        console.print(f"\n  [bold green]★ 定时签到已启动，按 Ctrl+C 停止[/bold green]\n")

        # 持续循环：运行待触发任务 + 显示倒计时
        while True:
            schedule.run_pending()
            show_countdown(schedule_times)
    else:
        # ── 立即模式：立即执行一次签到后退出 ──
        console.print("  [bold yellow]★ 未配置定时时间，立即开始签到…[/bold yellow]\n")
        job()
        input("\n  手动签到已结束，按回车关闭窗口…")


if __name__ == "__main__":
    main()
