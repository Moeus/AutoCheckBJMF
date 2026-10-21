import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capture_signin import Recorder, capture
from core.session import AccountSessions
from test_signin import COOKIE, COURSE, LOCATIONS, SUCCESS, SIGNED_TASK, SequenceAdapter
from test_cooldown import COOLDOWN


class CaptureTests(unittest.TestCase):
    @patch("capture_signin.time.sleep")
    def test_actual_signed_detail_stops_before_post(self, _):
        adapter = SequenceAdapter([(200, COURSE, {}), (200, SIGNED_TASK, {})])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, AccountSessions() as sessions:
            sessions.get(COOKIE).mount("http://", adapter)
            with patch("capture_signin.AccountSessions", return_value=sessions):
                result = capture({"cookies": [COOKIE], "locations": LOCATIONS}, "111026", 1, 1, None, Path(directory) / "capture")
        self.assertEqual(result["status"], "stopped")
        self.assertEqual([r.method for r in adapter.requests], ["GET", "GET"])

    def test_redaction_preserves_html_tag_structure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            recorder = Recorder(Path(directory) / "capture", COOKIE)
            html = '<script src="https://example.com/api?key=private-key"></script><p>未签到</p>'
            self.assertEqual(recorder.clean(html), '<script src="https://example.com/api?key=<redacted>"></script><p>未签到</p>')

    @patch("capture_signin.time.sleep")
    def test_captures_before_submit_after_redirects_and_diff(self, _):
        adapter = SequenceAdapter([
            (302, "redirect", {"Location": "/student/course/111026/punchs?ready=1"}),
            (200, COURSE, {}), (200, "<title>签到</title>还没签到", {}),
            (200, SUCCESS, {}), (200, "<title>签到</title>我已经签到过啦", {}),
            (200, "<title>课程</title>我已经签到过啦", {}),
        ])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "capture"
            with AccountSessions() as sessions:
                sessions.get(COOKIE).mount("http://", adapter)
                with patch("capture_signin.AccountSessions", return_value=sessions):
                    result = capture({"cookies": [COOKIE], "locations": LOCATIONS}, "111026", 1, 1, None, output)
            self.assertEqual(result["status"], "captured")
            self.assertEqual(result["http_responses"], 6)
            self.assertEqual([r.method for r in adapter.requests].count("POST"), 1)
            self.assertIn("我已经签到过啦", (output / "task.diff").read_text(encoding="utf-8"))
            for path in output.iterdir():
                self.assertNotIn("remember-secret", path.read_text(encoding="utf-8"))
            post = json.loads((output / "04_submit.json").read_text(encoding="utf-8"))
            self.assertIn("lat=22.766885", post["request"]["body"])

    @patch("capture_signin.time.sleep")
    def test_cooldown_and_ambiguous_tasks_stop_without_submission(self, _):
        for body in [COOLDOWN, COURSE + "<a id='gps_btn_456'>另一签到</a>"]:
            with self.subTest(body=body), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                adapter = SequenceAdapter([(200, body, {})])
                with AccountSessions() as sessions:
                    sessions.get(COOKIE).mount("http://", adapter)
                    with patch("capture_signin.AccountSessions", return_value=sessions):
                        result = capture({"cookies": [COOKIE], "locations": LOCATIONS}, "111026", 1, 1, None, Path(directory) / "capture")
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(len(adapter.requests), 1)


if __name__ == "__main__":
    unittest.main()
