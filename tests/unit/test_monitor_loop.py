"""Scheduler and CLI argument tests without sleeps, sockets or ping processes."""

import unittest
from threading import Event
from unittest.mock import Mock

from nettracker.monitor.loop import main, run_periodic


class PeriodicTests(unittest.TestCase):
    def test_one_cycle_is_the_safe_default(self) -> None:
        cycle = Mock(return_value=2)
        wait = Mock(return_value=False)
        result = run_periodic(cycle, wait=wait)
        self.assertEqual((result.cycles, result.measurements), (1, 2))
        wait.assert_not_called()

    def test_multiple_cycles_wait_only_between_cycles(self) -> None:
        cycle = Mock(return_value=2)
        wait = Mock(return_value=False)
        result = run_periodic(cycle, cycles=3, interval_seconds=12, wait=wait)
        self.assertEqual((result.cycles, result.measurements), (3, 6))
        self.assertEqual(wait.call_count, 2)
        wait.assert_called_with(12)

    def test_stop_before_start_does_not_run_a_cycle(self) -> None:
        stop = Event()
        stop.set()
        cycle = Mock(return_value=1)
        self.assertEqual(run_periodic(cycle, stop=stop).cycles, 0)
        cycle.assert_not_called()

    def test_interruptible_wait_stops_continuous_mode(self) -> None:
        cycle = Mock(return_value=1)
        result = run_periodic(cycle, cycles=None, wait=lambda seconds: True)
        self.assertEqual(result.cycles, 1)
        self.assertEqual(cycle.call_count, 1)

    def test_stop_during_cycle_is_honored(self) -> None:
        stop = Event()

        def cycle() -> int:
            stop.set()
            return 1

        self.assertEqual(run_periodic(cycle, cycles=None, stop=stop).cycles, 1)

    def test_cycle_error_is_not_silenced_or_retried(self) -> None:
        cycle = Mock(side_effect=ValueError("fixture failure"))
        wait = Mock(return_value=False)
        with self.assertRaises(ValueError):
            run_periodic(cycle, cycles=3, wait=wait)
        self.assertEqual(cycle.call_count, 1)
        wait.assert_not_called()

    def test_keyboard_interrupt_keeps_completed_cycle_count(self) -> None:
        cycle = Mock(side_effect=[2, KeyboardInterrupt()])
        result = run_periodic(cycle, cycles=3, wait=lambda seconds: False)
        self.assertTrue(result.interrupted)
        self.assertEqual((result.cycles, result.measurements), (1, 2))

    def test_interrupt_during_wait_is_handled(self) -> None:
        wait = Mock(side_effect=KeyboardInterrupt())
        result = run_periodic(lambda: 1, cycles=2, wait=wait)
        self.assertTrue(result.interrupted)
        self.assertEqual(result.cycles, 1)

    def test_invalid_limits_do_not_run_cycles(self) -> None:
        cycle = Mock(return_value=1)
        for interval in (0, 9, 86401, True):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                run_periodic(cycle, interval_seconds=interval)
        for count in (0, -1, 1000001, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                run_periodic(cycle, cycles=count)
        cycle.assert_not_called()

    def test_cli_help_does_not_load_configuration(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_cli_requires_explicit_monitoring_authorization(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["--device-id", "1"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_refuses_invalid_interval_before_loading_configuration(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["--device-id", "1", "--enable-monitoring", "--interval-seconds", "0"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["--device-id", "1", "--enable-monitoring", "--cycles", "2", "--continuous"])
        self.assertEqual(caught.exception.code, 2)
