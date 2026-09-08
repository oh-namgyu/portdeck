"""Port discovery: every evidence kind, plus the ranking between them."""

import json
import os
import shutil
import tempfile
import unittest

from portdeck.discover import Discovery, discover, is_incidental, primary_port, scan_project


def write(root: str, rel: str, text: str) -> str:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class DiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="portdeck-test-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def project(self, name: str) -> str:
        path = os.path.join(self.root, name)
        os.makedirs(path, exist_ok=True)
        write(path, "requirements.txt", "flask\n")
        return path

    def ports(self, root: str):
        return scan_project(root)

    def test_env_file(self) -> None:
        root = self.project("envy")
        write(root, ".env", "DEBUG=1\nPORT=5123\n")
        self.assertEqual(primary_port(self.ports(root)), 5123)

    def test_flask_run_kwarg(self) -> None:
        root = self.project("flasky")
        write(root, "app.py", "app.run(host='0.0.0.0', port=5200)\n")
        self.assertEqual(primary_port(self.ports(root)), 5200)

    def test_express_listen(self) -> None:
        root = self.project("nodey")
        write(root, "server.js", "app.listen(3210, () => {})\n")
        self.assertEqual(primary_port(self.ports(root)), 3210)

    def test_typed_constant(self) -> None:
        root = self.project("typed")
        write(root, "config.py", "PORT: int = 6040\n")
        self.assertEqual(primary_port(self.ports(root)), 6040)

    def test_constant_with_expression(self) -> None:
        root = self.project("argvy")
        write(root, "serve.py",
              "import sys\nPORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6140\n")
        self.assertEqual(primary_port(self.ports(root)), 6140)

    def test_npm_script_flag(self) -> None:
        root = self.project("vitey")
        write(root, "package.json", json.dumps({"scripts": {"dev": "vite --port 5173"}}))
        self.assertEqual(primary_port(self.ports(root)), 5173)

    def test_npm_script_bare_server_port(self) -> None:
        root = self.project("statix")
        write(root, "package.json",
              json.dumps({"scripts": {"start": "python3 -m http.server 6070"}}))
        self.assertEqual(primary_port(self.ports(root)), 6070)

    def test_json_config_key(self) -> None:
        root = self.project("configgy")
        write(root, "config.json", json.dumps({"port": 5074, "debug": True}))
        self.assertEqual(primary_port(self.ports(root)), 5074)

    def test_compose_mapping_wins_over_constant(self) -> None:
        root = self.project("composed")
        write(root, "docker-compose.yml", 'services:\n  web:\n    ports:\n      - "8081:80"\n')
        write(root, "config.py", "PORT = 9999\n")
        self.assertEqual(primary_port(self.ports(root)), 8081)

    def test_listen_beats_env_default(self) -> None:
        root = self.project("mixed")
        write(root, ".env", "PORT=1111\n")
        write(root, "server.js", "app.listen(2222)\n")
        self.assertEqual(primary_port(self.ports(root)), 2222)

    def test_test_fixture_is_not_the_project_port(self) -> None:
        root = self.project("fixtured")
        write(root, "watcher.py", "PORT = 5039\n")
        write(root, "verify_steps.py", 'cmd = "python3 -m http.server 9098"\n')
        self.assertEqual(primary_port(self.ports(root)), 5039)

    def test_fixture_used_when_nothing_else_exists(self) -> None:
        root = self.project("onlyfixture")
        write(root, "tests/server.js", "app.listen(4321)\n")
        self.assertEqual(primary_port(self.ports(root)), 4321)

    def test_implausible_numbers_are_ignored(self) -> None:
        root = self.project("noise")
        write(root, "app.py", "PORT = 7\n")
        self.assertIsNone(primary_port(self.ports(root)))

    def test_evidence_points_at_the_source(self) -> None:
        root = self.project("evident")
        write(root, "app.py", "app.run(port=5200)\n")
        found = Discovery(root, self.ports(root))
        self.assertEqual(found.port, 5200)
        self.assertEqual(found.evidence[0].file, "app.py")
        self.assertEqual(found.evidence[0].line, 1)
        self.assertEqual(found.source, "scan:listen")

    def test_discover_walks_roots_and_stops_at_projects(self) -> None:
        self.project("alpha")
        write(os.path.join(self.root, "alpha"), ".env", "PORT=5001\n")
        self.project("beta")
        write(os.path.join(self.root, "beta"), ".env", "PORT=5002\n")
        found = {d.name: d.port for d in discover([self.root], depth=2)}
        self.assertEqual(found, {"alpha": 5001, "beta": 5002})

    def test_skipped_directories_are_not_scanned(self) -> None:
        root = self.project("skipper")
        write(root, "node_modules/pkg/index.js", "app.listen(9999)\n")
        self.assertIsNone(primary_port(self.ports(root)))

    def test_commented_out_ports_are_ignored(self) -> None:
        root = self.project("commented")
        write(root, ".env", "# PORT=5999\n")
        write(root, "app.py", "# app.run(port=5998)\n// PORT = 5997\n")
        self.assertIsNone(primary_port(self.ports(root)))

    def test_commented_line_does_not_beat_real_code(self) -> None:
        root = self.project("mixed-comments")
        write(root, "app.py", "# app.run(port=1111)\napp.run(port=2222)\n")
        self.assertEqual(primary_port(self.ports(root)), 2222)

    def test_is_incidental(self) -> None:
        self.assertTrue(is_incidental("tests/app.py"))
        self.assertTrue(is_incidental("verify_steps.py"))
        self.assertTrue(is_incidental("src/app.test.js"))
        self.assertFalse(is_incidental("src/app.py"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
