import json
import re
import traceback
from http.cookies import CookieError

from .session import parse_cookie
from .timezone import TIMEZONE_LABEL, beijing_now
from .ui import console


def report_failure(logger, message, *, method="", url="", response=None,
                   exception=None, raw_cookie=""):
    """始终打印完整诊断并写日志；正文不截断，凭据值脱敏。"""
    responses = [*response.history, response] if response is not None else []
    secrets = set()

    def collect_cookies(value):
        try:
            secrets.update(parse_cookie(value).values())
        except CookieError:
            pass

    collect_cookies(raw_cookie)
    for item in responses:
        collect_cookies(item.headers.get("Set-Cookie", ""))
        secrets.update(cookie.value for cookie in item.cookies)
        if item.request is not None:
            collect_cookies(item.request.headers.get("Cookie", ""))

    def redact(value):
        text = str(value)
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            text = text.replace(secret, "<redacted>")
        return re.sub(
            r'''(?i)([?&](?:token|access_token|code|key|password|session|sessionid)=)[^&#\s"'<>]*''',
            r"\1<redacted>", text,
        )

    def headers_text(headers):
        return json.dumps({
            name: "<redacted>" if name.lower() in {
                "cookie", "set-cookie", "authorization", "proxy-authorization"
            } else redact(value)
            for name, value in headers.items()
        }, ensure_ascii=False, indent=2)

    lines = [
        f"[{beijing_now().isoformat(sep=' ', timespec='milliseconds')}] {TIMEZONE_LABEL}",
        f"错误：{message}",
        f"请求：{method} {url}",
    ]
    if responses:
        lines.append(f"重定向次数：{len(response.history)}")
        for index, item in enumerate(responses):
            lines.extend([
                f"--- {'最终响应' if item is response else f'重定向 {index + 1}'} ---",
                f"URL：{item.url}",
                f"HTTP：{item.status_code} {item.reason}",
            ])
            if item.request is not None:
                lines.extend([
                    f"实际请求：{item.request.method} {item.request.url}",
                    f"请求头：{headers_text(item.request.headers)}",
                ])
                if item.request.body is not None:
                    body = item.request.body
                    if isinstance(body, bytes):
                        body = body.decode("utf-8", errors="replace")
                    lines.append(f"请求正文：{body}")
            lines.extend([
                f"响应头：{headers_text(item.headers)}",
                f"响应编码：{item.encoding}",
                "响应正文（完整，凭据脱敏）：",
                item.text,
            ])
    else:
        lines.append("未收到 HTTP 响应。")
    if exception is not None:
        lines.append("异常堆栈：")
        lines.append("".join(traceback.format_exception(
            type(exception), exception, exception.__traceback__
        )))

    details = redact("\n".join(lines))
    console.print(details, style="red", markup=False, highlight=False)
    logger.error(details)
