import copy
from datetime import timedelta
from http.cookies import SimpleCookie

import requests

from .constants import COOKIE_KEY
from .timezone import beijing_now


class _SiteCookieJar(requests.cookies.RequestsCookieJar):
    def set_cookie(self, cookie, *args, **kwargs):
        # 服务端 Domain=k8n.cn 会被解析成 .k8n.cn；与初始 Cookie 统一，
        # 否则同名新旧凭据会一起发送。保留 domain_specified 等作用域标记。
        if cookie.domain == ".k8n.cn":
            cookie = copy.copy(cookie)
            cookie.domain = "k8n.cn"
        return super().set_cookie(cookie, *args, **kwargs)

    def clear(self, domain=None, path=None, name=None):
        # 过期的 Set-Cookie 会直接调用 clear，而不会经过 set_cookie。
        if domain == ".k8n.cn":
            domain = "k8n.cn"
        return super().clear(domain, path, name)

    def copy(self):
        jar = _SiteCookieJar()
        jar.set_policy(self.get_policy())
        jar.update(self)
        return jar


class _AccountSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.cookies = _SiteCookieJar()

    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        # Requests 合并 Cookie 时会新建普通 jar，换回本站 jar，使重定向
        # 中的 Set-Cookie 也遵循相同规则。
        jar = _SiteCookieJar()
        jar.update(prepared._cookies)
        prepared.headers.pop("Cookie", None)
        prepared.prepare_cookies(jar)
        return prepared


def parse_cookie(raw_cookie: str) -> dict[str, str]:
    """兼容配置向导生成的单个 Cookie 和手动填写的完整 Cookie。"""
    parsed = SimpleCookie()
    parsed.load(raw_cookie)
    return {name: item.value for name, item in parsed.items()}


class AccountSessions:
    """同一账号跨班级、跨调度轮次复用 Cookie jar，账号之间完全隔离。"""

    def __init__(self):
        self._sessions: dict[str, requests.Session] = {}
        self._completed: set[tuple[str, str, str]] = set()
        self.cooldown_until = None

    def defer_requests(self, minutes: int):
        # 限流可能按 IP 共享，因此暂停本进程全部账号/班级；额外留一分钟余量。
        until = beijing_now() + timedelta(minutes=minutes + 1)
        if self.cooldown_until is None or until > self.cooldown_until:
            self.cooldown_until = until

    def is_cooling_down(self) -> bool:
        return self.cooldown_until is not None and beijing_now() < self.cooldown_until

    def is_completed(self, raw_cookie: str, class_id: str, match_id: str) -> bool:
        return (raw_cookie, str(class_id), str(match_id)) in self._completed

    def mark_completed(self, raw_cookie: str, class_id: str, match_id: str):
        self._completed.add((raw_cookie, str(class_id), str(match_id)))

    def get(self, raw_cookie: str) -> requests.Session:
        if raw_cookie not in self._sessions:
            cookies = parse_cookie(raw_cookie)
            if not cookies.get(COOKIE_KEY):
                raise ValueError(f"未找到有效的 {COOKIE_KEY} Cookie")
            session = _AccountSession()
            for name, value in cookies.items():
                # 使用站点域名，避免无域名 Cookie 与服务器更新值同时发送。
                session.cookies.set(name, value, domain="k8n.cn", path="/")
            self._sessions[raw_cookie] = session
        return self._sessions[raw_cookie]

    def close(self):
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._completed.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
