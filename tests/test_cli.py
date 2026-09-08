"""End-to-end command runs against a temporary registry."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from portdeck import cli, doctor, live


def run(argv, registry):
    """Run a command and return (exit code, stdout)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
        code = cli.main(["--registry", registry] + argv)
    return code, buffer.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="portdeck-cli-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.registry = os.path.join(self.dir, "registry.json")
        self.workspace = os.path.join(self.dir, "workspace")
        os.makedirs(self.workspace)
        # Nothing is listening in these tests unless a case says otherwise.
        patcher = mock.patch.object(live, "listening_ports", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def project(self, name: str, files: dict) -> str:
        root = os.path.join(self.workspace, name)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def read_registry(self) -> dict:
        with open(self.registry, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_no_command_prints_help(self) -> None:
        code, out = run([], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("usage: portdeck", out)

    def test_ls_on_empty_registry_suggests_a_scan(self) -> None:
        code, out = run(["ls"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("portdeck scan", out)

    def test_add_then_ls(self) -> None:
        run(["add", "api", "5000", "--path", self.workspace], self.registry)
        code, out = run(["ls"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("api", out)
        self.assertIn("5000", out)

    def test_add_is_persisted(self) -> None:
        run(["add", "api", "5000"], self.registry)
        self.assertEqual(self.read_registry()["projects"][0]["name"], "api")

    def test_rm_removes_the_entry(self) -> None:
        run(["add", "api", "5000"], self.registry)
        code, _out = run(["rm", "api"], self.registry)
        self.assertEqual(code, 0)
        self.assertEqual(self.read_registry()["projects"], [])

    def test_rm_unknown_target_fails(self) -> None:
        code, _out = run(["rm", "ghost"], self.registry)
        self.assertEqual(code, 2)

    def test_scan_reports_without_writing(self) -> None:
        self.project("alpha", {".env": "PORT=5100\n", "requirements.txt": "flask\n"})
        code, out = run(["scan", self.workspace], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("5100", out)
        self.assertFalse(os.path.exists(self.registry))

    def test_scan_write_creates_entries(self) -> None:
        self.project("alpha", {".env": "PORT=5100\n", "requirements.txt": "flask\n"})
        code, out = run(["scan", self.workspace, "--write"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("added alpha :5100", out)
        self.assertEqual(self.read_registry()["projects"][0]["port"], 5100)

    def test_scan_write_is_idempotent(self) -> None:
        self.project("alpha", {".env": "PORT=5100\n", "requirements.txt": "flask\n"})
        run(["scan", self.workspace, "--write"], self.registry)
        _code, out = run(["scan", self.workspace, "--write"], self.registry)
        self.assertIn("1 unchanged", out)

    def test_doctor_exits_1_on_high_severity(self) -> None:
        run(["add", "a", "5000"], self.registry)
        run(["add", "b", "5000"], self.registry)
        code, out = run(["doctor"], self.registry)
        self.assertEqual(code, 1)
        self.assertIn("collision", out)

    def test_doctor_exits_0_when_clean(self) -> None:
        run(["add", "a", "5000"], self.registry)
        code, out = run(["doctor"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("no problems found", out)

    def test_doctor_json_output_is_a_list(self) -> None:
        run(["add", "a", "5000"], self.registry)
        run(["add", "b", "5000"], self.registry)
        _code, out = run(["--json", "doctor"], self.registry)
        payload = json.loads(out)
        self.assertEqual(payload[0]["check"], "collision")

    def test_map_prints_routes(self) -> None:
        root = self.project("api", {"app.py": "@app.route('/health')\ndef h(): pass\n"})
        run(["add", "api", "5000", "--path", root], self.registry)
        code, out = run(["map", "api"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("/health", out)

    def test_map_accepts_a_path(self) -> None:
        root = self.project("api", {"app.py": "@app.route('/health')\ndef h(): pass\n"})
        code, out = run(["map", root], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("/health", out)

    def test_map_unknown_target_fails(self) -> None:
        code, _out = run(["map", "ghost"], self.registry)
        self.assertEqual(code, 2)

    def test_map_mermaid(self) -> None:
        root = self.project("api", {"app.py": "@app.route('/health')\ndef h(): pass\n"})
        _code, out = run(["map", root, "--mermaid"], self.registry)
        self.assertTrue(out.startswith("flowchart LR"))

    def test_graph_mermaid_contains_the_edge(self) -> None:
        hub = self.project("hub", {"app.py": "x = 1\n"})
        caller = self.project("caller", {"c.py": "U='http://127.0.0.1:5038/x'\n"})
        run(["add", "hub", "5038", "--path", hub], self.registry)
        run(["add", "caller", "6000", "--path", caller], self.registry)
        _code, out = run(["graph", "--mermaid"], self.registry)
        self.assertIn("n_caller -->|:5038| n_hub", out)

    def test_who_reports_a_free_port(self) -> None:
        with mock.patch.object(live, "owner_of", return_value=None):
            code, out = run(["who", "5999"], self.registry)
        self.assertEqual(code, 0)
        self.assertIn("free", out)

    def test_who_reports_the_holder(self) -> None:
        held = live.Listener(5999, 4242, "node")
        with mock.patch.object(live, "owner_of", return_value=held), \
             mock.patch.object(live, "cwd_of", return_value="/tmp/app"):
            _code, out = run(["who", "5999"], self.registry)
        self.assertIn("node", out)
        self.assertIn("4242", out)
        self.assertIn("/tmp/app", out)

    def test_registry_flag_works_after_the_subcommand(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
            cli.main(["add", "api", "5000", "--registry", self.registry])
        self.assertEqual(self.read_registry()["projects"][0]["name"], "api")

    def test_json_flag_works_after_the_subcommand(self) -> None:
        run(["add", "api", "5000"], self.registry)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
            cli.main(["ls", "--json", "--registry", self.registry])
        self.assertEqual(json.loads(buffer.getvalue())[0]["name"], "api")

    def test_paths_are_stored_relative_to_home(self) -> None:
        home = os.path.expanduser("~")
        inside = os.path.join(home, ".portdeck-test-tmp")
        os.makedirs(inside, exist_ok=True)
        self.addCleanup(shutil.rmtree, inside, True)
        run(["add", "homey", "5000", "--path", inside], self.registry)
        self.assertTrue(self.read_registry()["projects"][0]["path"].startswith("~/"))


class DoctorScanFlagTest(unittest.TestCase):
    """`doctor --scan ROOT` folds discovery findings into the report."""

    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="portdeck-cli-scan-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.registry = os.path.join(self.dir, "registry.json")
        patcher = mock.patch.object(doctor.live, "listening_ports", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unregistered_projects_are_reported(self) -> None:
        root = os.path.join(self.dir, "workspace", "beta")
        os.makedirs(root)
        with open(os.path.join(root, ".env"), "w", encoding="utf-8") as fh:
            fh.write("PORT=7100\n")
        with open(os.path.join(root, "requirements.txt"), "w", encoding="utf-8") as fh:
            fh.write("flask\n")
        _code, out = run(["doctor", "--scan", os.path.dirname(root)], self.registry)
        self.assertIn("unregistered", out)
        self.assertIn("7100", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
