import io
import logging
import tempfile
import unittest
from datetime import datetime
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict
from rich.console import Console

from core.constants import COOKIE_KEY
from core.diagnostics import report_failure
from core.logger import setup_logger
from core.session import AccountSessions
from core.signin import qiandao, run_all_classes
from core.timezone import BEIJING_TZ


COOKIE = f"{COOKIE_KEY}=remember-secret"
LOCATIONS = [{"lat": 22.766885, "lng": 108.451339, "acc": "10"}]
COURSE = "<title>课程签到</title><a id='gps_btn_123'>签到</a>"
SUCCESS = "<div id='title'>签到成功</div>"
SIGNED_COURSE = (Path(__file__).parent / "fixtures/course_signed.html").read_text(encoding="utf-8")
SIGNED_TASK = (Path(__file__).parent / "fixtures/task_signed.html").read_text(encoding="utf-8")


class SequenceAdapter(BaseAdapter):
    """通过真实 Session.prepare/send/redirect/CookieJar 流程，无外网请求。"""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = False

    def send(self, request, **kwargs):
        self.requests.append(request)
        status, body, headers = next(self.responses)
        response = requests.Response()
        response.status_code = status
        response._content = body.encode("utf-8")
        response.encoding = "utf-8"
        response.reason = "test response"
        response.url = request.url
        response.request = request
        response.headers = CaseInsensitiveDict(headers)
        msg = Message()
        for key, value in headers.items():
            msg[key] = value
        response.raw = SimpleNamespace(
            _original_response=SimpleNamespace(msg=msg), close=lambda: None,
        )
        return response

    def close(self):
        self.closed = True


@patch("core.signin.time.sleep")
@patch("core.signin.console")
@patch("core.diagnostics.console")
class SigninTests(unittest.TestCase):
    def run_sign(self, sessions, locations=LOCATIONS):
        return qiandao(
            "111026", [COOKIE], locations, "", False, MagicMock(), sessions=sessions,
        )

    def test_session_cookie_survives_post_second_round_and_other_class(self, *_):
        adapter = SequenceAdapter([
            (200, COURSE, {"Set-Cookie": "session=first-session; Path=/"}),
            (200, SUCCESS, {"Set-Cookie": "session=updated-session; Path=/"}),
            (200, COURSE.replace("123", "456"), {}),
            (200, SUCCESS, {}),
            (200, "<title>暂无签到</title>", {}),
        ])
        with AccountSessions() as sessions, patch("core.signin.send_success_notifications") as notify:
            sessions.get(COOKIE).mount("http://", adapter)
            for _ in range(2):
                run_all_classes(
                    ["111026"], [COOKIE], LOCATIONS, "", False, MagicMock(),
                    retry_failures=False, sessions=sessions,
                )
            qiandao("136341", [COOKIE], LOCATIONS, "", False, MagicMock(), sessions=sessions)
            self.assertEqual(notify.call_count, 2)
        self.assertTrue(adapter.closed)
        self.assertIn("session=first-session", adapter.requests[1].headers["Cookie"])
        for request in adapter.requests[2:]:
            self.assertIn("session=updated-session", request.headers["Cookie"])
        self.assertEqual([r.method for r in adapter.requests], ["GET", "POST", "GET", "POST", "GET"])

    def test_server_refresh_of_remember_cookie_is_not_overwritten(self, *_):
        adapter = SequenceAdapter([
            (200, COURSE, {"Set-Cookie": f"{COOKIE_KEY}=renewed-secret; Path=/"}),
            (200, SUCCESS, {}),
            (200, "<title>暂无签到</title>", {}),
        ])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            self.run_sign(sessions)
            self.run_sign(sessions)
        for request in adapter.requests[1:]:
            self.assertIn(f"{COOKIE_KEY}=renewed-secret", request.headers["Cookie"])
            self.assertNotIn("remember-secret", request.headers["Cookie"])

    def test_cookie_domain_variants_replace_old_value_including_redirect(self, *_):
        for domain in ["", "Domain=k8n.cn;", "Domain=.k8n.cn;"]:
            with self.subTest(domain=domain), AccountSessions() as sessions:
                adapter = SequenceAdapter([
                    (302, "", {
                        "Set-Cookie": f"{COOKIE_KEY}=renewed-secret; {domain} Path=/",
                        "Location": "/student/course/111026/punchs?ready=1",
                    }),
                    (200, COURSE, {}),
                    (200, SUCCESS, {}),
                ])
                sessions.get(COOKIE).mount("http://", adapter)
                self.assertEqual(self.run_sign(sessions), ([], 0))
                for request in adapter.requests[1:]:
                    self.assertEqual(request.headers["Cookie"], f"{COOKIE_KEY}=renewed-secret")

    def test_accounts_are_isolated_and_initial_full_cookie_is_kept(self, *_):
        with AccountSessions() as sessions:
            first = sessions.get(COOKIE + "; browser_session=browser-secret")
            second = sessions.get(f"{COOKIE_KEY}=other-account")
            first.cookies.set("session", "first-only", domain="k8n.cn", path="/")
            self.assertEqual(first.cookies.get("browser_session"), "browser-secret")
            self.assertIsNone(second.cookies.get("session"))
            self.assertIs(first, sessions.get(COOKIE + "; browser_session=browser-secret"))
            request = first.prepare_request(requests.Request("GET", "http://example.com/"))
            self.assertNotIn("Cookie", request.headers)

    def test_server_can_expire_cookie_without_restoring_config_value(self, *_):
        with AccountSessions() as sessions:
            session = sessions.get(COOKIE)
            session.mount("http://", SequenceAdapter([
                (200, "<title>出错</title>", {
                    "Set-Cookie": f"{COOKIE_KEY}=deleted; Domain=k8n.cn; Path=/; Max-Age=0",
                }),
            ]))
            self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
            self.assertIsNone(session.cookies.get(COOKIE_KEY))
            self.assertIsNone(sessions.get(COOKIE).cookies.get(COOKIE_KEY))

    def test_error_page_is_not_reported_as_definite_cookie_expiry(self, output, *_):
        adapter = SequenceAdapter([(200, "<title>出错</title>访问频繁，请稍后重试", {})])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
        details = output.print.call_args.args[0]
        self.assertIn("不能仅凭此判断 Cookie 过期", details)
        self.assertIn("访问频繁，请稍后重试", details)

    def test_http_errors_missing_result_and_business_failure_are_queued(self, *_):
        for responses in [
            [(429, "<title>Too many requests</title>", {})],
            [(200, COURSE, {}), (500, "server error", {})],
            [(200, COURSE, {}), (200, "<p>unexpected format</p>", {})],
            [(200, COURSE, {}), (200, "<div id='title'>不在签到范围</div>", {})],
        ]:
            with self.subTest(responses=responses), AccountSessions() as sessions:
                sessions.get(COOKIE).mount("http://", SequenceAdapter(responses))
                self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))

    def test_later_location_success_clears_failure_and_failures_are_deduplicated(self, *_):
        for last_body, expected in [(SUCCESS, []), ("<div id='title'>失败</div>", [COOKIE])]:
            with self.subTest(last_body=last_body), AccountSessions() as sessions:
                sessions.get(COOKIE).mount("http://", SequenceAdapter([
                    (200, COURSE, {}), (500, "server error", {}), (200, last_body, {}),
                ]))
                self.assertEqual(self.run_sign(sessions, LOCATIONS * 2), (expected, 0))

    def test_login_redirect_reports_chain_and_body(self, output, *_):
        adapter = SequenceAdapter([
            (302, "redirect body", {"Location": "/login", "Set-Cookie": "session=redirect-secret"}),
            (200, "<title>登录</title>请登录", {}),
        ])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
        details = output.print.call_args.args[0]
        for text in ["重定向次数：1", "HTTP：302", "http://k8n.cn/login", "redirect body", "请登录"]:
            self.assertIn(text, details)
        self.assertNotIn("redirect-secret", details)
        self.assertNotIn("remember-secret", details)

    def test_network_error_prints_traceback_and_retries_next_round(self, output, *_):
        with AccountSessions() as sessions:
            session = sessions.get(COOKIE)
            with patch.object(session, "get", side_effect=requests.Timeout("read timed out")):
                self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
            session.mount("http://", SequenceAdapter([(200, "<title>暂无签到</title>", {})]))
            self.assertEqual(self.run_sign(sessions), ([], 0))
        details = output.print.call_args.args[0]
        self.assertIn("Traceback (most recent call last)", details)
        self.assertIn("requests.exceptions.Timeout: read timed out", details)
        self.assertIn("未收到 HTTP 响应", details)

    def test_missing_title_with_sign_button_still_signs(self, *_):
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", SequenceAdapter([
                (200, "<a id='gps_btn_123'>签到</a>", {}), (200, SUCCESS, {}),
            ]))
            self.assertEqual(self.run_sign(sessions), ([], 0))

    def test_completed_task_is_skipped_but_new_task_on_same_page_is_submitted(self, output, *_):
        adapter = SequenceAdapter([
            (200, COURSE, {}), (200, SUCCESS, {}),
            (200, COURSE, {}),
            (200, COURSE + "<a id='gps_btn_456'>新签到</a>", {}), (200, SUCCESS, {}),
        ])
        with AccountSessions() as sessions, patch("core.signin.send_success_notifications") as notify:
            sessions.get(COOKIE).mount("http://", adapter)
            for _ in range(3):
                self.assertEqual(self.run_sign(sessions), ([], 0))
            self.assertEqual(notify.call_count, 2)
        posts = [r for r in adapter.requests if r.method == "POST"]
        self.assertEqual([r.url.rsplit("/", 1)[-1] for r in posts], ["123", "456"])
        output.print.assert_not_called()

    def test_already_signed_course_page_is_not_an_error_and_does_not_block_next_task(self, output, *_):
        for title in ["", "<title>出错</title>"]:
            with self.subTest(title=title), AccountSessions() as sessions:
                adapter = SequenceAdapter([
                    (200, title + "<div>我已经<span>签到过啦</span>！</div>", {}),
                    (200, COURSE, {}), (200, SUCCESS, {}),
                ])
                sessions.get(COOKIE).mount("http://", adapter)
                with patch("core.signin.send_success_notifications") as notify:
                    self.assertEqual(self.run_sign(sessions), ([], 0))
                    notify.assert_not_called()
                    self.assertEqual(self.run_sign(sessions), ([], 0))
                    notify.assert_called_once()
                self.assertEqual([r.method for r in adapter.requests], ["GET", "GET", "POST"])
        output.print.assert_not_called()

    def test_already_signed_post_is_cached_without_retries_or_notification(self, output, *_):
        for body in [
            "<title>出错</title><p>我已经签到过啦</p>",
            "<div id='title'>我已经签到过啦！</div>",
            SIGNED_TASK,
        ]:
            with self.subTest(body=body), AccountSessions() as sessions:
                adapter = SequenceAdapter([
                    (200, COURSE, {}), (200, body, {}), (200, COURSE, {}),
                ])
                sessions.get(COOKIE).mount("http://", adapter)
                with patch("core.signin.send_success_notifications") as notify:
                    self.assertEqual(self.run_sign(sessions, LOCATIONS * 2), ([], 0))
                    self.assertEqual(self.run_sign(sessions), ([], 0))
                    notify.assert_not_called()
                self.assertEqual([r.method for r in adapter.requests], ["GET", "POST", "GET"])
        output.print.assert_not_called()

    def test_actual_signed_course_reports_completed_then_accepts_new_task(self, errors, output, *_):
        adapter = SequenceAdapter([
            (200, SIGNED_COURSE, {}), (200, COURSE.replace("123", "456"), {}), (200, SUCCESS, {}),
        ])
        with AccountSessions() as sessions, patch("core.signin.send_success_notifications") as notify:
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([], 0))
            notify.assert_not_called()
            messages = "\n".join(str(call.args[0]) for call in output.print.call_args_list)
            self.assertIn("1 项任务已签到", messages)
            self.assertNotIn("暂无进行中的签到任务", messages)
            self.assertEqual(self.run_sign(sessions), ([], 0))
            notify.assert_called_once()
        self.assertEqual([r.method for r in adapter.requests], ["GET", "GET", "POST"])
        self.assertTrue(adapter.requests[-1].url.endswith("/456"))
        errors.print.assert_not_called()

    def test_signed_card_does_not_hide_other_active_card(self, errors, *_):
        # 即使已完成卡片保留旧按钮，也只提交同页未完成任务。
        signed_with_button = SIGNED_COURSE.replace(
            '<div class="punch-action">', '<div class="punch-action"><a id="gps_btn_123">旧按钮</a>',
        )
        page = signed_with_button + COURSE.replace("123", "456")
        adapter = SequenceAdapter([(200, page, {}), (200, SUCCESS, {})])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([], 0))
        self.assertEqual(len(adapter.requests), 2)
        self.assertTrue(adapter.requests[-1].url.endswith("/456"))
        errors.print.assert_not_called()

    def test_completed_task_does_not_skip_other_account_or_class(self, *_):
        other_cookie = f"{COOKIE_KEY}=other-account"
        first_adapter = SequenceAdapter([
            (200, COURSE, {}), (200, SUCCESS, {}),
            (200, COURSE, {}), (200, SUCCESS, {}),
        ])
        second_adapter = SequenceAdapter([(200, COURSE, {}), (200, SUCCESS, {})])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", first_adapter)
            sessions.get(other_cookie).mount("http://", second_adapter)
            self.assertEqual(self.run_sign(sessions), ([], 0))
            for class_id, cookie in [("136341", COOKIE), ("111026", other_cookie)]:
                self.assertEqual(qiandao(
                    class_id, [cookie], LOCATIONS, "", False, MagicMock(), sessions=sessions,
                ), ([], 0))
        self.assertEqual([r.method for r in first_adapter.requests], ["GET", "POST", "GET", "POST"])
        self.assertEqual([r.method for r in second_adapter.requests], ["GET", "POST"])

    def test_failed_task_is_still_attempted_next_round(self, *_):
        adapter = SequenceAdapter([
            (200, COURSE, {}), (200, "<div id='title'>不在签到范围</div>", {}),
            (200, COURSE, {}), (200, SUCCESS, {}),
        ])
        with AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
            self.assertEqual(self.run_sign(sessions), ([], 0))
        self.assertEqual([r.method for r in adapter.requests], ["GET", "POST", "GET", "POST"])

    def test_historical_done_text_or_script_does_not_hide_active_task_or_error(self, output, *_):
        with AccountSessions() as sessions:
            adapter = SequenceAdapter([
                (200, COURSE + "<p>历史记录：我已经签到过啦</p>", {}), (200, SUCCESS, {}),
                (200, "<title>出错</title><script>var message='我已经签到过啦';</script>", {}),
            ])
            sessions.get(COOKIE).mount("http://", adapter)
            self.assertEqual(self.run_sign(sessions), ([], 0))
            self.assertEqual(self.run_sign(sessions), ([COOKIE], 0))
        output.print.assert_called_once()


class DiagnosticsTests(unittest.TestCase):
    def test_full_body_literal_markup_millisecond_beijing_time_and_redaction(self):
        body = "[red]literal[/red]" + "正文" * 5000 + "remember-secret server-secret END"
        session = requests.Session()
        session.mount("http://", SequenceAdapter([
            (500, body, {"Set-Cookie": "session=server-secret; Path=/"}),
        ]))
        response = session.get("http://k8n.cn/test?token=private-token")
        logger = MagicMock()
        output = io.StringIO()
        fixed_time = datetime(2026, 10, 20, 8, 49, 0, 123000, tzinfo=BEIJING_TZ)
        with patch("core.diagnostics.console", Console(file=output, width=120)), patch(
            "core.diagnostics.beijing_now", return_value=fixed_time,
        ):
            report_failure(
                logger, "测试失败", method="GET", url=response.url,
                response=response, raw_cookie=COOKIE,
            )
        details = logger.error.call_args.args[0]
        self.assertIn("2026-10-20 08:49:00.123+08:00", details)
        self.assertIn("正文" * 5000, details)
        self.assertIn(" END", details)
        self.assertIn("[red]literal[/red]", output.getvalue())
        for secret in ["remember-secret", "server-secret", "private-token"]:
            self.assertNotIn(secret, details)
            self.assertNotIn(secret, output.getvalue())
        session.close()

    def test_errors_are_logged_even_with_debug_disabled_without_duplicate_handlers(self):
        isolated_logger = logging.Logger("diagnostic-test")
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            log_path = Path(directory).resolve() / "test.log"
            try:
                with patch("core.logger.LOG_PATH", log_path), patch(
                    "core.logger.logging.getLogger", return_value=isolated_logger,
                ):
                    logger = setup_logger(False)
                    setup_logger(False)
                    logger.error("错误详情")
                    self.assertEqual(len(logger.handlers), 1)
                    self.assertFalse(logger.propagate)
                saved = log_path.read_text(encoding="utf-8")
                self.assertIn("+08:00", saved)
                self.assertIn("错误详情", saved)
            finally:
                for handler in isolated_logger.handlers:
                    handler.close()


if __name__ == "__main__":
    unittest.main()
