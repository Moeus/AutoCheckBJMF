import re

from bs4 import BeautifulSoup


def cooldown_minutes(body: str) -> int | None:
    """识别服务器返回的冷却正文，不把普通 HTTP 200 当作正常页面。"""
    text = re.sub(r"\s+", "", BeautifulSoup(body, "html.parser").get_text())
    if "再访问" not in text or "冷却" not in text:
        return None
    match = re.search(r"(\d+)分钟[^，。；;]{0,20}再访问", text)
    return int(match.group(1)) if match else None
