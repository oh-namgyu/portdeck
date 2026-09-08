"""Live layer — lsof field parsing and the no-lsof fallback."""

import unittest
from unittest import mock

from portdeck import doctor, live

LISTEN_OUTPUT = "\n".join([
    "p668", "cControlCenter", "udev", "n*:5000",
    "p85276", "cPython", "udev", "n127.0.0.1:4400",
    "n[::1]:5039",
])
CWD_OUTPUT = "\n".join(["p668", "fcwd", "n/", "p85276", "fcwd", "n/home/you/code/api"])


class ParseTest(unittest.TestCase):
    def test_listening_ports_parses_field_output(self) -> None:
        with mock.patch.object(live, "_run_lsof", return_value=LISTEN_OUTPUT):
            ports = live.listening_ports()
        self.assertEqual(sorted(ports), [4400, 5000, 5039])
        self.assertEqual(ports[5000].command, "ControlCenter")
        self.assertEqual(ports[4400].pid, 85276)

    def test_ipv6_names_resolve_to_a_port(self) -> None:
        with mock.patch.object(live, "_run_lsof", return_value=LISTEN_OUTPUT):
            self.assertEqual(live.listening_ports()[5039].pid, 85276)

    def test_empty_output_is_no_listeners(self) -> None:
        with mock.patch.object(live, "_run_lsof", return_value=""):
            self.assertEqual(live.listening_ports(), {})

    def test_cwds_of_maps_each_pid(self) -> None:
        with mock.patch.object(live, "_run_lsof", return_value=CWD_OUTPUT) as run:
            cwds = live.cwds_of([668, 85276, 668])
        self.assertEqual(cwds, {668: "/", 85276: "/home/you/code/api"})
        self.assertEqual(run.call_count, 1)  # one call for every pid

    def test_cwds_of_without_pids_does_not_shell_out(self) -> None:
        with mock.patch.object(live, "_run_lsof") as run:
            self.assertEqual(live.cwds_of([]), {})
        run.assert_not_called()

    def test_system_hint_for_airplay(self) -> None:
        self.assertIn("AirPlay", live.system_hint("ControlCenter", 5000))
        self.assertEqual(live.system_hint("node", 5000), "")


class FallbackTest(unittest.TestCase):
    def test_running_is_probed_when_lsof_is_missing(self) -> None:
        with mock.patch.object(live, "has_lsof", return_value=False), \
             mock.patch.object(live, "is_listening", return_value=True) as probe:
            self.assertTrue(doctor.is_running(5000, {}))
        probe.assert_called_once_with(5000)

    def test_no_probe_when_lsof_is_available(self) -> None:
        with mock.patch.object(live, "has_lsof", return_value=True), \
             mock.patch.object(live, "is_listening") as probe:
            self.assertFalse(doctor.is_running(5000, {}))
        probe.assert_not_called()

    def test_listener_wins_without_probing(self) -> None:
        with mock.patch.object(live, "is_listening") as probe:
            self.assertTrue(doctor.is_running(5000, {5000: live.Listener(5000, 1, "x")}))
        probe.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
