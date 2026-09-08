"""Diagnostics — each check, with the live socket layer stubbed out."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from portdeck import doctor
from portdeck.live import Listener
from portdeck.registry import Entry, Registry


def listener(port: int, pid: int = 111, command: str = "python") -> Listener:
    return Listener(port, pid, command)


class DoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="portdeck-doc-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def project(self, name: str, files: dict) -> str:
        root = os.path.join(self.dir, name)
        os.makedirs(root, exist_ok=True)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def test_collision_is_high_severity(self) -> None:
        reg = Registry([Entry("a", 5000), Entry("b", 5000)], "")
        found = doctor.check_collisions(reg)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "high")
        self.assertIn("a, b", found[0].message)

    def test_no_collision_for_distinct_ports(self) -> None:
        reg = Registry([Entry("a", 5000), Entry("b", 5001)], "")
        self.assertEqual(doctor.check_collisions(reg), [])

    def test_missing_path(self) -> None:
        reg = Registry([Entry("gone", 5000, os.path.join(self.dir, "nope"))], "")
        found = doctor.check_missing_paths(reg)
        self.assertEqual([f.check for f in found], ["missing-path"])

    def test_drift_reports_the_code_port(self) -> None:
        root = self.project("drifty", {"app.py": "app.run(port=6000)\n",
                                       "requirements.txt": "flask\n"})
        reg = Registry([Entry("drifty", 5000, root)], "")
        found = doctor.check_drift(reg)
        self.assertEqual(len(found), 1)
        self.assertIn("registry says 5000 but code says 6000", found[0].message)

    def test_no_drift_when_code_agrees(self) -> None:
        root = self.project("agree", {"app.py": "app.run(port=5000)\n"})
        reg = Registry([Entry("agree", 5000, root)], "")
        self.assertEqual(doctor.check_drift(reg), [])

    def test_squatter_when_holder_runs_elsewhere(self) -> None:
        root = self.project("mine", {"app.py": "x = 1\n"})
        reg = Registry([Entry("mine", 5000, root)], "")
        with mock.patch.object(doctor.live, "listening_ports",
                               return_value={5000: listener(5000)}), \
             mock.patch.object(doctor.live, "cwds_of", return_value={111: "/somewhere/else"}):
            found = doctor.check_squatters(reg)
        self.assertEqual([f.check for f in found], ["squatter"])

    def test_no_squatter_when_holder_runs_in_the_project(self) -> None:
        root = self.project("mine", {"app.py": "x = 1\n"})
        reg = Registry([Entry("mine", 5000, root)], "")
        with mock.patch.object(doctor.live, "listening_ports",
                               return_value={5000: listener(5000)}), \
             mock.patch.object(doctor.live, "cwds_of",
                               return_value={111: os.path.join(root, "sub")}):
            self.assertEqual(doctor.check_squatters(reg), [])

    def test_squatter_fix_names_a_known_system_holder(self) -> None:
        root = self.project("air", {"app.py": "x = 1\n"})
        reg = Registry([Entry("air", 5000, root)], "")
        with mock.patch.object(doctor.live, "listening_ports",
                               return_value={5000: listener(5000, 668, "ControlCenter")}), \
             mock.patch.object(doctor.live, "cwds_of", return_value={668: "/"}):
            found = doctor.check_squatters(reg)
        self.assertIn("AirPlay", found[0].fix)

    def test_orphan_lists_unregistered_listeners(self) -> None:
        reg = Registry([Entry("known", 5000)], "")
        with mock.patch.object(doctor.live, "listening_ports",
                               return_value={5000: listener(5000),
                                             6000: listener(6000, 222, "node")}), \
             mock.patch.object(doctor.live, "cwds_of", return_value={}):
            found = doctor.check_orphans(reg)
        self.assertEqual([f.port for f in found], [6000])

    def test_unregistered_projects_from_a_scan(self) -> None:
        root = self.project("fresh", {".env": "PORT=7000\n", "requirements.txt": "x\n"})
        from portdeck.discover import Discovery, scan_project
        found = doctor.check_unregistered(Registry([], ""),
                                          [Discovery(root, scan_project(root))])
        self.assertEqual([f.port for f in found], [7000])

    def test_run_sorts_by_severity(self) -> None:
        reg = Registry([Entry("a", 5000), Entry("b", 5000)], "")
        with mock.patch.object(doctor.live, "listening_ports",
                               return_value={9000: listener(9000)}), \
             mock.patch.object(doctor.live, "cwds_of", return_value={}):
            found = doctor.run(reg)
        self.assertEqual([f.severity for f in found], ["high", "low"])

    def test_entry_status_marks_foreign_holders(self) -> None:
        root = self.project("mine", {"app.py": "x = 1\n"})
        entry = Entry("mine", 5000, root)
        status = doctor.entry_status(entry, {5000: listener(5000)}, {111: "/elsewhere"})
        self.assertTrue(status["running"])
        self.assertFalse(status["owned"])

    def test_entry_status_when_stopped(self) -> None:
        status = doctor.entry_status(Entry("mine", 5000), {})
        self.assertFalse(status["running"])
        self.assertTrue(status["owned"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
