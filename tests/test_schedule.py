import copy
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import make_config
import main
from core.config import load_config
from core.config_wizard import save_config
from core.scheduler import DailyScheduler, get_countdown_status, validate_schedule_config
from core.signin import run_all_classes
from core.timezone import BEIJING_TZ, beijing_now
from core.logger import BeijingFormatter


def dt(value):
    return datetime.fromisoformat("2026-10-14 " + value).replace(tzinfo=BEIJING_TZ)


def window(start="08:00", end="08:30", interval=60):
    return {"start": start, "end": end, "interval_seconds": interval}


def scheduler(now, *windows):
    return DailyScheduler({"schedule_windows": list(windows) or [window()]}, dt(now))


class SchedulerTests(unittest.TestCase):
    def test_before_start_and_start_inclusive(self):
        task = scheduler("07:59:00")
        self.assertEqual(task.next_run, dt("08:00:00"))
        self.assertFalse(task.is_due(dt("07:59:59")))
        self.assertTrue(task.is_due(dt("08:00:00")))

    def test_mid_window_start_aligns_to_origin(self):
        self.assertEqual(scheduler("08:03:14").next_run, dt("08:04:00"))
        self.assertEqual(scheduler("08:03:00").next_run, dt("08:03:00"))

    def test_non_minute_interval(self):
        self.assertEqual(scheduler("08:01:01", window(interval=45)).next_run, dt("08:01:30"))

    def test_end_exclusive(self):
        task = scheduler("08:29:00")
        self.assertFalse(task.is_due(dt("08:30:00")))
        self.assertEqual(task.next_run, datetime(2026, 10, 15, 8, tzinfo=BEIJING_TZ))

    def test_long_job_skips_missed_ticks_without_drift(self):
        task = scheduler("08:00:00")
        task.advance(dt("08:03:27"))
        self.assertEqual(task.next_run, dt("08:04:00"))
        task.advance(dt("08:35:00"))
        self.assertEqual(task.next_run, datetime(2026, 10, 15, 8, tzinfo=BEIJING_TZ))

    def test_suspend_skips_expired_ticks(self):
        task = scheduler("07:59:00")
        self.assertFalse(task.is_due(dt("08:10:23")))
        self.assertEqual(task.next_run, dt("08:11:00"))

    def test_poll_delay_within_tick_is_allowed(self):
        self.assertTrue(scheduler("08:00:00").is_due(dt("08:00:00.250")))

    def test_overnight_previous_day_and_end(self):
        cfg = {"schedule_windows": [window("23:50", "00:10", 60)]}
        task = DailyScheduler(cfg, dt("00:03:20"))
        self.assertEqual(task.next_run, dt("00:04:00"))
        task.advance(dt("00:10:00"))
        self.assertEqual(task.next_run, dt("23:50:00"))

    def test_multiple_windows_and_same_tick_deduplication(self):
        task = scheduler("07:00:00", window(), window(interval=30), window("12:00", "12:20"))
        self.assertTrue(task.is_due(dt("08:00:00")))
        task.advance(dt("08:00:05"))
        self.assertEqual(task.next_run, dt("08:00:30"))
        task.advance(dt("08:30:00"))
        self.assertEqual(task.next_run, dt("12:00:00"))

    def test_interval_longer_than_window_runs_only_at_start(self):
        task = scheduler("08:00:00", window(interval=7200))
        self.assertTrue(task.is_due(dt("08:00:00")))
        task.advance(dt("08:00:01"))
        self.assertEqual(task.next_run, datetime(2026, 10, 15, 8, tzinfo=BEIJING_TZ))

    def test_legacy_and_empty_windows_override(self):
        task = DailyScheduler({"scheduletimes": ["08:00", "12:30"]}, dt("09:00:00"))
        self.assertEqual(task.next_run, dt("12:30:00"))
        task = DailyScheduler({"scheduletimes": ["08:00"], "schedule_windows": []}, dt("07:00:00"))
        self.assertIsNone(task.next_run)

    def test_countdown_matches_actual_tick(self):
        task = scheduler("08:03:14")
        text, delay = get_countdown_status(task.next_run, dt("08:03:14"))
        self.assertIn("08:04:00", text)
        self.assertIn("46 秒", text)
        self.assertEqual(delay, 1)


class TimezoneTests(unittest.TestCase):
    def test_current_clock_explicitly_uses_east_eight(self):
        instant = datetime(2026, 10, 14, tzinfo=timezone.utc)
        with patch("core.timezone.datetime") as clock:
            clock.now.side_effect = lambda tz: instant.astimezone(tz)
            self.assertEqual(beijing_now(), dt("08:00:00"))
            self.assertEqual(beijing_now().utcoffset(), timedelta(hours=8))
            clock.now.assert_called_with(BEIJING_TZ)

    def test_utc_input_schedules_on_beijing_calendar_date(self):
        # UTC 13 日 23:59 是北京时间 14 日 07:59。
        now = datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)
        for cfg in ({"schedule_windows": [window()]}, {"scheduletimes": ["08:00"]}):
            with self.subTest(cfg=cfg):
                task = DailyScheduler(cfg, now)
                self.assertEqual(task.next_run, dt("08:00:00"))
                self.assertTrue(task.is_due(datetime(2026, 10, 14, tzinfo=timezone.utc)))

    def test_overnight_window_with_utc_input(self):
        task = DailyScheduler(
            {"schedule_windows": [window("23:50", "00:10")]},
            datetime(2026, 10, 13, 16, 3, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(task.next_run, dt("00:04:00"))
        task.advance(datetime(2026, 10, 13, 16, 10, tzinfo=timezone.utc))
        self.assertEqual(task.next_run, dt("23:50:00"))

    def test_countdown_converts_display_to_beijing(self):
        text, _ = get_countdown_status(
            dt("08:00:00"), datetime(2026, 10, 13, 23, 59, tzinfo=timezone.utc)
        )
        self.assertIn("北京时间（UTC+8）", text)
        self.assertIn("2026-10-14 07:59:00", text)
        self.assertIn("0 小时 1 分 0 秒", text)

    def test_log_timestamp_is_beijing_regardless_of_host_timezone(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
        record.created = datetime(2026, 10, 13, 16, tzinfo=timezone.utc).timestamp()
        self.assertEqual(BeijingFormatter().formatTime(record), "2026-10-14 00:00:00.000+08:00")


class ConfigTests(unittest.TestCase):
    def test_saved_window_config_loads_without_legacy_field(self):
        cfg = {"classes": [], "cookies": [], "locations": [], "schedule_windows": [window()]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "config.json"
            with patch("core.config_wizard.CONFIG_PATH", path), patch("core.config_wizard.console"):
                save_config(cfg)
            with patch("core.config.CONFIG_PATH", path):
                self.assertEqual(load_config(), cfg)

    def test_normalizes_both_formats(self):
        cfg = {"schedule_windows": [window("8：00", "8 30")]}
        validate_schedule_config(cfg)
        self.assertEqual(cfg["schedule_windows"], [window()])
        cfg = {"scheduletimes": ["8:0"]}
        validate_schedule_config(cfg)
        self.assertEqual(cfg["scheduletimes"], ["08:00"])

    def test_invalid_config_rejected(self):
        cases = [None, {}, [None], [window("24:00")], [window(end="08:00")]]
        cases += [[window(interval=i)] for i in (0, -1, 1.5, True, "60", None)]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_schedule_config({"schedule_windows": value})

    @patch("make_config.console")
    def test_wizard_add_modify_delete_preserves_input(self, _):
        original = {"schedule_windows": [window()]}
        snapshot = copy.deepcopy(original)
        actions = ["添加区间", "修改区间", 0, "删除区间", 1, "完成配置"]
        selections = [MagicMock(ask=MagicMock(return_value=a)) for a in actions]
        with patch("make_config.questionary.select", side_effect=selections), patch(
            "make_config.prompt_schedule_window", side_effect=[window("12:00", "12:20"), window(interval=30)]
        ):
            result = make_config.configure_schedule(original)
        self.assertEqual(result, {"schedule_windows": [window(interval=30)]})
        self.assertEqual(original, snapshot)

    @patch("make_config.console")
    def test_wizard_retains_legacy_or_switches(self, _):
        cfg = {"scheduletimes": ["08:00"]}
        with patch("make_config.confirm_or_default", return_value=False):
            self.assertEqual(make_config.configure_schedule(cfg), cfg)
        with patch("make_config.confirm_or_default", return_value=True), patch(
            "make_config.questionary.select"
        ) as select:
            select.return_value.ask.return_value = "完成配置"
            self.assertEqual(make_config.configure_schedule(cfg), {"schedule_windows": []})

    @patch("make_config.console")
    def test_wizard_reprompts_invalid_step(self, _):
        with patch("make_config.prompt_input", side_effect=["8：00", "8 30", "0", "1.5", "60"]):
            self.assertEqual(make_config.prompt_schedule_window(), window())

    @patch("make_config.console")
    def test_wizard_default_interval_and_edit_defaults(self, _):
        def use_defaults(message, **kwargs):
            return kwargs["default"]
        with patch("make_config.prompt_input", side_effect=use_defaults):
            self.assertEqual(make_config.prompt_schedule_window(window()), window())
        with patch("make_config.prompt_input", side_effect=["08:00", "08:30", "300"]) as prompt:
            self.assertEqual(make_config.prompt_schedule_window(), window(interval=300))
            self.assertEqual(prompt.call_args.kwargs["default"], "300")


class ExecutionTests(unittest.TestCase):
    def test_empty_windows_run_once_even_with_legacy_times(self):
        cfg = {"classes": [], "cookies": [], "locations": [],
               "schedule_windows": [], "scheduletimes": ["08:00"]}
        with patch.multiple(main, print_banner=MagicMock(), console=MagicMock(),
                            print_runtime_summary=MagicMock(), setup_logger=MagicMock()), \
             patch.object(main, "load_config", return_value=cfg), \
             patch.object(main, "send_lifecycle_notification"), \
             patch.object(main, "run_all_classes") as job, \
             patch("builtins.input", return_value=""):
            main.main()
            job.assert_called_once()
            self.assertTrue(job.call_args.kwargs["retry_failures"])

    @patch("core.signin.console")
    @patch("core.signin.time.sleep")
    @patch("core.signin.qiandao", return_value=(["failed-cookie"], 0))
    def test_window_mode_does_not_wait_for_internal_retries(self, sign, sleep, _):
        run_all_classes(["class"], [], [], "", False, logging.getLogger("test"), retry_failures=False)
        self.assertEqual(sign.call_count, 1)
        sleep.assert_not_called()

    @patch("core.signin.console")
    @patch("core.signin.time.sleep")
    @patch("core.signin.qiandao", return_value=(["failed-cookie"], 0))
    def test_default_retry_behavior_preserved(self, sign, sleep, _):
        run_all_classes(["class"], [], [], "", False, logging.getLogger("test"))
        self.assertEqual(sign.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 300])

    def test_main_connects_scheduler_and_disables_retries(self):
        cfg = {"classes": [], "cookies": [], "locations": [], "schedule_windows": [window()]}
        with patch.multiple(main, print_banner=MagicMock(), console=MagicMock(),
                            print_runtime_summary=MagicMock(), setup_logger=MagicMock(), Live=MagicMock()), \
             patch.object(main, "load_config", return_value=cfg), \
             patch.object(main, "send_lifecycle_notification") as notify, \
             patch.object(main, "beijing_now") as clock, \
             patch("core.scheduler.beijing_now") as scheduler_clock, \
             patch.object(main, "run_all_classes") as job, \
             patch.object(main.time, "sleep", side_effect=KeyboardInterrupt):
            scheduler_clock.return_value = dt("08:00:00")
            clock.side_effect = [dt("08:00:00"), dt("08:00:20"), dt("08:00:20")]
            main.main()
            job.assert_called_once()
            self.assertFalse(job.call_args.kwargs["retry_failures"])
            self.assertEqual(notify.call_count, 2)
            self.assertIn("每 60 秒", notify.call_args.args[-1][0])

    def test_main_reuses_account_sessions_across_two_ticks_and_closes_on_exit(self):
        cfg = {"classes": [], "cookies": [], "locations": [], "schedule_windows": [window()]}
        with patch.multiple(main, print_banner=MagicMock(), console=MagicMock(),
                            print_runtime_summary=MagicMock(), setup_logger=MagicMock(), Live=MagicMock()), \
             patch.object(main, "load_config", return_value=cfg), \
             patch.object(main, "send_lifecycle_notification"), \
             patch.object(main, "AccountSessions") as pool, \
             patch.object(main, "DailyScheduler") as scheduler_factory, \
             patch.object(main, "run_all_classes") as job:
            scheduler_factory.return_value.is_due.side_effect = [True, True, KeyboardInterrupt]
            main.main()
            self.assertEqual(job.call_count, 2)
            pool.assert_called_once()
            for call in job.call_args_list:
                self.assertIs(call.kwargs["sessions"], pool.return_value)
            pool.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
