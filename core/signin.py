import logging
import random
import re
import time
from http.cookies import CookieError
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from rich.panel import Panel

from .diagnostics import report_failure
from .cooldown import cooldown_minutes
from .location import modify_decimal_part
from .notifications import send_success_notifications
from .session import AccountSessions
from .timezone import TIMEZONE_LABEL, beijing_now
from .ui import console


def _already_signed(soup: BeautifulSoup) -> bool:
    # 文案可能跨 HTML 标签或换行；只检查页面文本，不匹配脚本中的字符串。
    text = re.sub(r"\s+", "", soup.get_text("", strip=True))
    return bool(re.search(r"我(?:已经|已)签到过啦", text))


def _completed_card(card) -> bool:
    if card is None:
        return False
    status = card.select_one(".punch-status")
    return bool(
        status and status.get_text(strip=True) == "已签到"
        and ("punch-card--success" in card.get("class", [])
             or card.select_one(".punch-success-info") is not None)
    )


def _show_cooldown(sessions):
    console.print(
        f"{beijing_now():%Y-%m-%d %H:%M:%S} {TIMEZONE_LABEL} | "
        f"请求过于频繁，服务器要求冷却；暂停所有账号/班级请求至 "
        f"{sessions.cooldown_until:%Y-%m-%d %H:%M:%S}（含 1 分钟余量），届时按签到计划恢复。",
        style="yellow", markup=False,
    )


def _handle_cooldown(response, sessions, logger, context):
    minutes = cooldown_minutes(response.text)
    if minutes is None:
        return False
    sessions.defer_requests(minutes)
    _show_cooldown(sessions)
    logger.warning(
        "%s | 请求过于频繁，服务器要求冷却 %s 分钟；暂停至 %s | %s",
        context, minutes, sessions.cooldown_until.isoformat(), response.url,
    )
    return True


def signin_headers(class_id: str) -> dict:
    return {
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
    }


def qiandao(
    class_id: str,
    cookies: list,
    locations: list,
    pushplus_token: str,
    debug: bool,
    logger: logging.Logger,
    feishu_webhook: str = "",
    *,
    sessions: AccountSessions | None = None,
) -> tuple[list, int]:
    """
    对单个班级执行所有账号的签到。
    """
    if sessions is None:
        with AccountSessions() as owned_sessions:
            return qiandao(
                class_id, cookies, locations, pushplus_token, debug, logger,
                feishu_webhook, sessions=owned_sessions,
            )

    if sessions.is_cooling_down():
        _show_cooldown(sessions)
        return [], 0

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

        context = f"账号[{uid + 1}{username_tag}] | 班级[{class_id}]"

        def fail(message, *, method="GET", request_url=url, response=None, exception=None):
            report_failure(
                logger, f"{context} | {message}", method=method, url=request_url,
                response=response, exception=exception, raw_cookie=raw_cookie,
            )

        def already_done(match_id=None):
            task_label = f" | 签到ID[{match_id}]" if match_id is not None else ""
            message = (
                f"{beijing_now():%Y-%m-%d %H:%M:%S} {TIMEZONE_LABEL} | "
                f"{context}{task_label} | 已签到，跳过重复提交"
            )
            console.print(message, style="green", markup=False)
            logger.info(message)

        try:
            session = sessions.get(raw_cookie)
        except (ValueError, CookieError) as e:
            null_count += 1
            fail("Cookie 配置无效", exception=e)
            continue

        if debug:
            console.print(
                f"  [Debug] 账号 {uid + 1} 会话 Cookie 名称："
                f"{sorted({cookie.name for cookie in session.cookies})}",
                markup=False,
            )

        headers = signin_headers(class_id)

        try:
            response = session.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            fail("课程页面网络请求失败", response=e.response, exception=e)
            error_cookies.append(raw_cookie)
            continue

        console.print(f"  [cyan]▶[/cyan] 班级 [bold]{class_id}[/bold] 课程页面响应：[dim]{response.status_code}[/dim]")

        if _handle_cooldown(response, sessions, logger, context):
            return error_cookies, null_count

        if response.status_code != 200:
            fail("课程页面 HTTP 请求失败", response=response)
            error_cookies.append(raw_cookie)
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find("title")
        completed_count = sum(_completed_card(card) for card in soup.select(".punch-card"))
        gps_buttons = [btn for btn in soup.find_all("a", id=re.compile(r"^gps_btn_\d+$"))
                       if not _completed_card(btn.find_parent(class_="punch-card"))]
        all_matches = list(dict.fromkeys(btn["id"].removeprefix("gps_btn_") for btn in gps_buttons))
        title = title_tag.get_text(strip=True) if title_tag else ""
        if "login" in urlsplit(response.url).path.lower() or "登录" in title:
            fail("课程请求返回登录页面，请检查登录状态", response=response)
            error_cookies.append(raw_cookie)
            continue
        already_signed_page = _already_signed(soup)
        if already_signed_page and not all_matches:
            # 无任务 ID 时只结束本次检查，不把整个班级永久标记为完成。
            already_done()
            continue
        if not already_signed_page and not completed_count and ("出错" in title or (not title and not all_matches)):
            fail(
                f"课程页面异常（标题：{title or '缺失'}），不能仅凭此判断 Cookie 过期",
                response=response,
            )
            error_cookies.append(raw_cookie)
            continue

        if completed_count:
            # 实际已签到卡片不再包含任务 ID，不能据此缓存整个班级或猜测 ID。
            message = (
                f"{beijing_now():%Y-%m-%d %H:%M:%S} {TIMEZONE_LABEL} | {context} | "
                f"当前页面有 {completed_count} 项任务已签到，跳过已完成任务"
            )
            console.print(message, style="green", markup=False)
            logger.info(message)

        console.print(f"  [cyan]▶[/cyan] 找到 GPS 签到 ID：[bold cyan]{all_matches}[/bold cyan]")

        if not all_matches:
            if not completed_count:
                console.print(f"  [yellow]ℹ[/yellow]  班级 [bold]{class_id}[/bold] 暂无进行中的签到任务。")
            continue

        for match_id in all_matches:
            if sessions.is_completed(raw_cookie, class_id, match_id):
                already_done(match_id)
                continue
            task_succeeded = False
            if not locations:
                fail(f"签到 ID[{match_id}] 未配置定位点")
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
                    sign_resp = session.post(sign_url, headers=headers, data=payload, timeout=15)
                except requests.RequestException as e:
                    fail(
                        f"签到 ID[{match_id}] 网络请求失败", method="POST",
                        request_url=sign_url, response=e.response, exception=e,
                    )
                    continue

                if _handle_cooldown(sign_resp, sessions, logger, context):
                    return error_cookies, null_count

                console.print(
                    f"  [cyan]▶[/cyan] 签到请求已发送："
                    f"ID[[bold]{match_id}[/bold]] "
                    f"坐标[[cyan]{new_lat:.6f}, {new_lng:.6f}[/cyan]] "
                    f"海拔[[dim]{acc}[/dim]]"
                )
                logger.info(f"UID[{uid+1}{username_tag}] | 班级[{class_id}] | 签到ID[{match_id}] | 坐标[{new_lat},{new_lng}]")

                if sign_resp.status_code == 200:
                    result_soup = BeautifulSoup(sign_resp.text, "html.parser")
                    if _already_signed(result_soup):
                        task_succeeded = True
                        sessions.mark_completed(raw_cookie, class_id, match_id)
                        already_done(match_id)
                        break
                    div_tag = result_soup.find("div", id="title")
                    if div_tag:
                        result_text = div_tag.text.strip()
                        if result_text == "签到成功":
                            task_succeeded = True
                            sessions.mark_completed(raw_cookie, class_id, match_id)
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

                        fail(
                            f"签到 ID[{match_id}] 返回结果：{result_text}",
                            method="POST", request_url=sign_url, response=sign_resp,
                        )
                        continue

                    fail(
                        f"签到 ID[{match_id}] 未找到结果标签，无法确认签到成功",
                        method="POST", request_url=sign_url, response=sign_resp,
                    )
                else:
                    fail(
                        f"签到 ID[{match_id}] HTTP 请求失败",
                        method="POST", request_url=sign_url, response=sign_resp,
                    )
            if not task_succeeded and raw_cookie not in error_cookies:
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
    retry_failures: bool = True,
    *,
    sessions: AccountSessions | None = None,
):
    """
    遍历所有班级；区间模式关闭内部重试，由下一轮调度重试。
    """
    if sessions is None:
        with AccountSessions() as owned_sessions:
            return run_all_classes(
                classes, cookies, locations, pushplus_token, debug, logger,
                feishu_webhook, retry_failures, sessions=owned_sessions,
            )

    if sessions.is_cooling_down():
        _show_cooldown(sessions)
        return

    console.rule(f"[bold cyan]开始签到  {beijing_now():%Y-%m-%d %H:%M:%S} {TIMEZONE_LABEL}[/bold cyan]")
    console.print(
        f"  班级数：[bold]{len(classes)}[/bold]  账号数：[bold]{len(cookies)}[/bold]  "
        f"定位点数：[bold]{len(locations)}[/bold]"
    )

    for class_id in classes:
        console.print(f"\n  [cyan]▶[/cyan] 开始签到班级：[bold cyan]{class_id}[/bold cyan]")
        error_cookies, null_count = qiandao(
            class_id, cookies, locations, pushplus_token, debug, logger, feishu_webhook,
            sessions=sessions,
        )

        if sessions.is_cooling_down():
            return

        if error_cookies and retry_failures:
            console.print(f"\n  [yellow]⚠[/yellow] 有 [bold]{len(error_cookies)}[/bold] 个账号签到失败，30秒后重试…")
            time.sleep(30)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger, feishu_webhook,
                sessions=sessions,
            )

            if sessions.is_cooling_down():
                return

        if error_cookies and retry_failures:
            console.print(f"\n  [yellow]⚠[/yellow] 仍有 [bold]{len(error_cookies)}[/bold] 个账号失败，5 分钟后最后一次重试…")
            time.sleep(300)
            error_cookies, _ = qiandao(
                class_id, error_cookies, locations, pushplus_token, debug, logger, feishu_webhook,
                sessions=sessions,
            )

            if sessions.is_cooling_down():
                return

        if error_cookies:
            console.print(Panel(
                f"[bold red]❌ 班级 {class_id}：仍有账号签到失败[/bold red]\n"
                f"{beijing_now():%Y-%m-%d %H:%M:%S} {TIMEZONE_LABEL}\n"
                "请查看上方完整错误信息或 AutoCheckBJMF.log。\n"
                + ("下一轮定时任务将重新尝试。" if not retry_failures else "本轮重试已结束。"),
                border_style="red", padding=(0, 2)
            ))
        elif null_count > 0:
            console.print(f"\n  [yellow]⚠[/yellow] 班级 [bold]{class_id}[/bold]：存在 {null_count} 个无效 Cookie，请检查配置。")
        else:
            console.print(Panel(
                f"[bold green]✅ 班级 {class_id}：本轮检查完成[/bold green]",
                border_style="green", padding=(0, 2)
            ))

    console.rule("[dim]签到结束[/dim]")
