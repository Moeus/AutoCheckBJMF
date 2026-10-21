import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from core.cooldown import cooldown_minutes
from core.session import AccountSessions
from core.signin import run_all_classes
from core.timezone import BEIJING_TZ
from test_signin import COOKIE, COURSE, LOCATIONS, SequenceAdapter


COOLDOWN = "119分钟完全后再访问该页面，冷却前访问一次会增加1分钟等待时间"


class CooldownTests(unittest.TestCase):
    def test_parse_exact_body_and_html_but_not_unrelated_text(self):
        for body in [COOLDOWN, '<p>119 分钟后再访问该页面</p><p>冷却前访问会增加等待时间</p>']:
            self.assertEqual(cooldown_minutes(body), 119)
        self.assertIsNone(cooldown_minutes("我已经签到过啦"))
        self.assertIsNone(cooldown_minutes("120分钟后开始签到"))

    @patch("core.signin.time.sleep")
    @patch("core.signin.console")
    @patch("core.diagnostics.console")
    def test_get_and_post_cooldown_stop_other_accounts_classes_retries_and_ticks(self, diagnostics, console, sleep):
        for responses in [[(200, COOLDOWN, {})], [(200, COURSE, {}), (200, COOLDOWN, {})]]:
            with self.subTest(responses=responses), AccountSessions() as sessions:
                now = datetime(2026, 10, 21, 8, 49, tzinfo=BEIJING_TZ)
                logger = MagicMock()
                adapter = SequenceAdapter(responses)
                sessions.get(COOKIE).mount("http://", adapter)
                with patch("core.session.beijing_now", return_value=now):
                    for _ in range(2):
                        run_all_classes(
                            ["111026", "136341"], [COOKIE, "invalid-second-account"], LOCATIONS,
                            "", False, logger, sessions=sessions,
                        )
                    self.assertEqual(sessions.cooldown_until, now + timedelta(minutes=120))
                self.assertEqual(len(adapter.requests), len(responses))
                logger.error.assert_not_called()
                logger.warning.assert_called_once()
                diagnostics.print.assert_not_called()
                self.assertNotIn(30, [call.args[0] for call in sleep.call_args_list])
                self.assertNotIn(300, [call.args[0] for call in sleep.call_args_list])
                # 到期后恢复下一次计划检查，而不是永久跳过。
                resumed = SequenceAdapter([(200, '<title>暂无签到</title>', {})])
                sessions.get(COOKIE).mount("http://", resumed)
                with patch("core.session.beijing_now", return_value=now + timedelta(minutes=120)):
                    run_all_classes(["111026"], [COOKIE], LOCATIONS, "", False, logger, sessions=sessions)
                self.assertEqual(len(resumed.requests), 1)


if __name__ == "__main__":
    unittest.main()
