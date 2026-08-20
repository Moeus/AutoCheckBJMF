import logging
from datetime import datetime

import requests

from .constants import PUSHPLUS_URL
from .location import format_location
from .ui import console


def send_pushplus_notification(token: str, title: str, content: str, logger: logging.Logger):
    """通过 PushPlus 发送通知。"""
    if not token:
        return

    try:
        response = requests.get(
            PUSHPLUS_URL,
            params={"token": token, "title": title, "content": content},
            timeout=10
        )
        response.raise_for_status()
        console.print("  [bold green]✔[/bold green] PushPlus 推送已发送")
        logger.info("PushPlus 推送已发送")
    except requests.RequestException as e:
        console.print(f"  [yellow]⚠[/yellow] PushPlus 推送失败，主流程继续执行：{e}")
        logger.warning(f"PushPlus 推送失败：{e}")


def send_feishu_notification(webhook: str, content: str, logger: logging.Logger):
    """通过飞书自定义机器人 Webhook 发送通知。"""
    if not webhook:
        return

    try:
        response = requests.post(
            webhook,
            json={"msg_type": "text", "content": {"text": content}},
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10
        )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError:
            data = {}

        status_code = data.get("code", data.get("StatusCode", 0))
        if status_code not in (0, "0", None):
            status_msg = data.get("msg", data.get("StatusMessage", "未知错误"))
            raise RuntimeError(f"{status_code}: {status_msg}")

        console.print("  [bold green]✔[/bold green] 飞书推送已发送")
        logger.info("飞书推送已发送")
    except (requests.RequestException, RuntimeError) as e:
        console.print(f"  [yellow]⚠[/yellow] 飞书推送失败，主流程继续执行：{e}")
        logger.warning(f"飞书推送失败：{e}")


def send_channel_notifications(
    pushplus_token: str,
    feishu_webhook: str,
    title: str,
    content: str,
    logger: logging.Logger,
):
    """向所有已配置的通知渠道发送消息。"""
    send_pushplus_notification(pushplus_token, title, content, logger)
    send_feishu_notification(feishu_webhook, content, logger)


def build_sign_success_content(
    user_label: str,
    class_id: str,
    match_id: str,
    result_text: str,
    lat: float,
    lng: float,
    acc: str,
) -> str:
    """构建详细的签到成功通知文本。"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    location_text = format_location(lat, lng, acc)
    return "\n".join([
        "🚀 **班级魔方签到成功**",
        f"⏱️ 完成时间：{timestamp}",
        f"👤 签到用户：{user_label}",
        f"🏫 班级 ID：{class_id}",
        f"🧾 签到事件：GPS签到（ID：{match_id}）",
        f"📍 使用位置：{location_text}",
        f"✅ 签到结果：{result_text}",
    ])


def send_success_notifications(
    pushplus_token: str,
    feishu_webhook: str,
    user_label: str,
    class_id: str,
    match_id: str,
    result_text: str,
    lat: float,
    lng: float,
    acc: str,
    logger: logging.Logger,
):
    """签到成功后发送所有已配置的通知渠道。"""
    title = "班级魔方自动签到"
    content = build_sign_success_content(user_label, class_id, match_id, result_text, lat, lng, acc)
    send_channel_notifications(pushplus_token, feishu_webhook, title, content, logger)


def send_lifecycle_notification(
    pushplus_token: str,
    feishu_webhook: str,
    event: str,
    mode: str,
    logger: logging.Logger,
    schedule_times: list | None = None,
):
    """脚本启动或关闭时发送运行状态通知。"""
    title = "AutoCheckBJMF 运行提醒"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    schedule_text = "、".join(schedule_times) if schedule_times else "未设置（立即模式）"
    content = "\n".join([
        f"🚀 **AutoCheckBJMF 脚本{event}**",
        f"⏱️ 通知时间：{timestamp}",
        f"🧭 运行模式：{mode}",
        f"📅 监听签到时间：{schedule_text}",
        f"✅ 当前状态：{event}",
    ])
    send_channel_notifications(pushplus_token, feishu_webhook, title, content, logger)
