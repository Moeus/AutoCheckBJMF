import logging
import random
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from rich.panel import Panel

from .constants import COOKIE_KEY
from .location import modify_decimal_part
from .notifications import send_success_notifications
from .ui import console


def qiandao(
    class_id: str,
    cookies: list,
    locations: list,
    pushplus_token: str,
    debug: bool,
    logger: logging.Logger,
    feishu_webhook: str = "",
) -> tuple[list, int]:
    """
    对单个班级执行所有账号的签到。
    """
    url = f"http://k8n.cn/student/course/{class_id}/punchs"
    error_cookies = []
    null_count = 0

    for uid, raw_cookie in enumerate(cookies):
        username_match = re.search(r"username=[^;]+", raw_cookie)
        username = username_match.group(0).split("=")[1] if username_match else ""
        username_tag = f" <{username}>" if username else ""
        user_label = f"用户{uid + 1}{username_tag}"

        time.sleep(random.randint(1, 3))
        console.print(
            f"\r  [bold yellow]★{uid+1}★[/bold yellow] {username_tag} [bold yellow]开始签到 ★{uid+1}★[/bold yellow]"
        )

        cookie_match = re.search(rf"{COOKIE_KEY}=[^;]+", raw_cookie)
        if not cookie_match:
            null_count += 1
            console.print(f"  [bold red]✗[/bold red] 未找到有效 Cookie，请检查账号 {uid+1} 的 Cookie 配置！")
            continue

        extracted_cookie = cookie_match.group(0)
        if debug:
            console.print(f"  [dim][Debug] Cookie: {extracted_cookie}[/dim]")

        headers = {
            "User-Agent": ("Mozilla/5.0 (Linux; Android 9; AKT-AK47 Build/USER-AK47; wv) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 "
                           "Mobile Safari/537.36 XWEB/1160065 MMWEBSDK/20231202 MMWEBID/1136 "
                           "MicroMessenger/8.0.47.2560(0x28002F35) WeChat/arm64 Weixin "
                           "NetType/4G Language/zh_CN ABI/arm64"),
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;"
                       "q=0.8,application/signed-exchange;v=b3;q=0.7"),
            "X-Requested-With": "com.tencent.mm",
            "Referer": f"http://k8n.cn/student/course/{class_id}",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh-SG;q=0.9,zh;q=0.8,en-SG;q=0.7,en-US;q=0.6,en;q=0.5",
            "Cookie": extracted_cookie,
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            console.print(f"  [bold red]✗[/bold red] 网络请求失败：{e}")
            error_cookies.append(raw_cookie)
            continue

        console.print(f"  [cyan]▶[/cyan] 班级 [bold]{class_id}[/bold] 课程页面响应：[dim]{response.status_code}[/dim]")

        soup = BeautifulSoup(response.text, "html.parser")
        all_matches = []
        title_tag = soup.find("title")
        if not title_tag or "出错" in title_tag.text:
            console.print(f"  [bold red]✗[/bold red] 登录状态异常（账号 {uid+1}），加入重试队列")
            logger.error(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 登录状态异常")
            error_cookies.append(raw_cookie)
            continue

        gps_btn = soup.find("a", id=re.compile(r"^gps_btn_\d+$"))
        if gps_btn:
            gps_id = re.compile(r"\d+").search(gps_btn.get("id")).group(0)
            all_matches.append(gps_id)

        console.print(f"  [cyan]▶[/cyan] 找到 GPS 签到 ID：[bold cyan]{all_matches}[/bold cyan]")

        if not all_matches:
            console.print(f"  [yellow]ℹ[/yellow]  班级 [bold]{class_id}[/bold] 暂无进行中的签到任务。")
            continue

        for match_id in all_matches:
            for loc in locations:
                new_lat = modify_decimal_part(loc["lat"])
                new_lng = modify_decimal_part(loc["lng"])
                acc = loc["acc"]

                sign_url = f"http://k8n.cn/student/punchs/course/{class_id}/{match_id}"
                payload = {
                    "id": match_id,
                    "lat": new_lat,
                    "lng": new_lng,
                    "acc": acc,
                    "res": "",
                    "gps_addr": "",
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
                    result_soup = BeautifulSoup(sign_resp.text, "html.parser")
                    div_tag = result_soup.find("div", id="title")
                    if div_tag:
                        result_text = div_tag.text.strip()
                        if result_text == "签到成功":
                            console.print(f"  [bold green]✔[/bold green] 签到结果：[bold green]{result_text}[/bold green]")
                            logger.info(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 签到结果：{result_text}")
                            send_success_notifications(
                                pushplus_token=pushplus_token,
                                feishu_webhook=feishu_webhook,
                                user_label=user_label,
                                class_id=class_id,
                                match_id=match_id,
                                result_text=result_text,
                                lat=new_lat,
                                lng=new_lng,
                                acc=acc,
                                logger=logger,
                            )
                            break

                        console.print(f"  [yellow]⚠[/yellow] 签到结果：[yellow]{result_text}[/yellow]")
                        logger.info(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 签到结果：{result_text}")
                        continue

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
    logger: logging.Logger,
    feishu_webhook: str = "",
):
    """
    遍历所有班级，依次执行签到，并对失败的 Cookie 重试最多两次。
    """
    console.rule(f"[bold cyan]开始签到  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/bold cyan]")
    console.print(
        f"  班级数：[bold]{len(classes)}[/bold]  账号数：[bold]{len(cookies)}[/bold]  "
        f"定位点数：[bold]{len(locations)}[/bold]"
    )

    for class_id in classes:
        console.print(f"\n  [cyan]▶[/cyan] 开始签到班级：[bold cyan]{class_id}[/bold cyan]")
        error_cookies, null_count = qiandao(
            class_id, cookies, locations, pushplus_token, debug, logger, feishu_webhook
        )

        if error_cookies:
            console.print(f"\n  [yellow]⚠[/yellow] 有 [bold]{len(error_cookies)}[/bold] 个账号签到失败，30秒后重试…")
            time.sleep(30)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger, feishu_webhook
            )

        if error_cookies:
            console.print(f"\n  [yellow]⚠[/yellow] 仍有 [bold]{len(error_cookies)}[/bold] 个账号失败，5 分钟后最后一次重试…")
            time.sleep(300)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger, feishu_webhook
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
