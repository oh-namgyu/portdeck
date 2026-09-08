"""Topology scanning — routes found, calls resolved, graph built."""

import json
import os
import shutil
import tempfile
import unittest

from portdeck import topology
from portdeck.registry import Entry, Registry


class TopologyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="portdeck-topo-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def project(self, name: str, files: dict) -> str:
        root = os.path.join(self.dir, name)
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return root

    def test_flask_routes(self) -> None:
        root = self.project("flasky", {
            "app.py": "@app.route('/api/search', methods=['POST'])\n"
                      "def search(): pass\n"
                      "@app.route('/')\ndef home(): pass\n"})
        topo = topology.scan(root)
        self.assertIn({"method": "POST", "path": "/api/search", "file": "app.py"},
                      topo["endpoints"])
        self.assertIn({"method": "GET", "path": "/", "file": "app.py"}, topo["endpoints"])

    def test_fastapi_decorators(self) -> None:
        root = self.project("fast", {"main.py": "@app.get('/items')\ndef items(): pass\n"})
        self.assertEqual(topology.scan(root)["endpoints"],
                         [{"method": "GET", "path": "/items", "file": "main.py"}])

    def test_express_routes(self) -> None:
        root = self.project("nodey", {"server.js": "app.post('/save', h)\n"})
        self.assertEqual(topology.scan(root)["endpoints"],
                         [{"method": "POST", "path": "/save", "file": "server.js"}])

    def test_next_app_router_route(self) -> None:
        root = self.project("nexty", {
            "app/api/todo/route.ts": "export async function GET() {}\n"})
        endpoints = topology.scan(root)["endpoints"]
        self.assertEqual(endpoints[0]["path"], "/api/todo")
        self.assertEqual(endpoints[0]["method"], "GET")

    def test_next_pages_router(self) -> None:
        root = self.project("pagey", {"pages/about.tsx": "export default function A() {}\n"})
        self.assertEqual(topology.scan(root)["endpoints"][0]["path"], "/about")

    def test_outbound_call_resolves_to_a_registered_project(self) -> None:
        other = self.project("other", {"app.py": "x = 1\n"})
        root = self.project("caller", {
            "client.py": "URL = 'http://localhost:4400/api/notify'\n"})
        reg = Registry([Entry("hub", 4400, other), Entry("caller", 6000, root)], "")
        calls = topology.scan(root, reg)["calls"]
        self.assertEqual(calls[0]["project"], "hub")
        self.assertTrue(calls[0]["local"])

    def test_outbound_call_to_unknown_port_has_no_project(self) -> None:
        root = self.project("caller", {"client.py": "U = 'http://localhost:9911/x'\n"})
        calls = topology.scan(root, Registry([], ""))["calls"]
        self.assertIsNone(calls[0]["project"])

    def test_remote_hosts_are_not_resolved_to_local_projects(self) -> None:
        root = self.project("caller", {"client.py": "U = 'http://example.com:4400/x'\n"})
        reg = Registry([Entry("hub", 4400, self.dir)], "")
        calls = topology.scan(root, reg)["calls"]
        self.assertIsNone(calls[0]["project"])
        self.assertFalse(calls[0]["local"])

    def test_self_calls_are_dropped(self) -> None:
        root = self.project("selfy", {"app.py": "U = 'http://localhost:6000/health'\n"})
        reg = Registry([Entry("selfy", 6000, root)], "")
        self.assertEqual(topology.scan(root, reg)["calls"], [])

    def test_entrypoints_and_layers(self) -> None:
        root = self.project("layered", {
            "app.py": "x = 1\n", "core/one.py": "y = 1\n", "core/two.py": "z = 1\n",
            "package.json": json.dumps({"main": "app.js", "scripts": {"start": "node app.js"}})})
        topo = topology.scan(root)
        kinds = {e["kind"] for e in topo["entrypoints"]}
        self.assertEqual(kinds, {"python", "package.main", "package.start"})
        self.assertEqual(topo["layers"][0], {"name": "core", "files": 2})

    def test_graph_builds_edges_between_projects(self) -> None:
        hub = self.project("hub", {"app.py": "@app.route('/api')\ndef a(): pass\n"})
        caller = self.project("caller", {"c.py": "U='http://127.0.0.1:4400/api'\n"})
        reg = Registry([Entry("hub", 4400, hub), Entry("caller", 6000, caller)], "")
        graph = topology.graph(reg)
        self.assertEqual(graph["edges"], [{"from": "caller", "to": "hub", "port": 4400}])
        self.assertEqual(sorted(n["name"] for n in graph["nodes"]), ["caller", "hub"])

    def test_graph_deduplicates_repeated_edges(self) -> None:
        hub = self.project("hub", {"app.py": "x = 1\n"})
        caller = self.project("caller", {
            "a.py": "U='http://127.0.0.1:4400/one'\n", "b.py": "V='http://127.0.0.1:4400/two'\n"})
        reg = Registry([Entry("hub", 4400, hub), Entry("caller", 6000, caller)], "")
        self.assertEqual(len(topology.graph(reg)["edges"]), 1)

    def test_truncation_is_reported(self) -> None:
        files = {"f{}.py".format(i): "x = 1\n" for i in range(5)}
        root = self.project("many", files)
        topo = topology.scan(root, max_files=3)
        self.assertTrue(topo["truncated"])
        self.assertEqual(topo["scanned"], 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
