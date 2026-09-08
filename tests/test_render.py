"""Rendering — alignment, colour policy, and mermaid escaping."""

import os
import unittest

from portdeck import render
from portdeck.doctor import Finding


class RenderTest(unittest.TestCase):
    def test_table_aligns_columns(self) -> None:
        text = render.table(["A", "B"], [["long-value", "x"], ["s", "y"]])
        lines = text.splitlines()
        self.assertEqual(lines[1], "long-value  x")
        self.assertEqual(lines[2], "s           y")

    def test_table_of_nothing_is_empty(self) -> None:
        self.assertEqual(render.table(["A"], []), "")

    def test_no_color_env_disables_painting(self) -> None:
        os.environ["NO_COLOR"] = "1"
        self.addCleanup(os.environ.pop, "NO_COLOR", None)
        self.assertEqual(render.paint("hi", "red"), "hi")

    def test_paint_applies_ansi_when_enabled(self) -> None:
        self.assertEqual(render.paint("hi", "red", True), "\033[31mhi\033[0m")

    def test_plural(self) -> None:
        self.assertEqual(render.plural(1, "file"), "1 file")
        self.assertEqual(render.plural(2, "file"), "2 files")

    def test_findings_reports_a_clean_bill(self) -> None:
        self.assertIn("no problems", render.findings([]))

    def test_findings_include_the_fix(self) -> None:
        text = render.findings([Finding("collision", "high", 5000, "clash", "move one")])
        self.assertIn("clash", text)
        self.assertIn("fix: move one", text)

    def test_graph_mermaid_hides_isolated_nodes(self) -> None:
        graph = {"nodes": [{"name": "a", "port": 1}, {"name": "b", "port": 2},
                           {"name": "lonely", "port": 3}],
                 "edges": [{"from": "a", "to": "b", "port": 2}]}
        text = render.graph_mermaid(graph)
        self.assertIn("n_a", text)
        self.assertNotIn("lonely", text)

    def test_graph_mermaid_sanitises_names(self) -> None:
        graph = {"nodes": [{"name": "my-app.v2", "port": 1}], "edges": []}
        self.assertIn("n_my_app_v2", render.graph_mermaid(graph))

    def test_graph_text_when_no_edges(self) -> None:
        self.assertIn("no cross-project calls",
                      render.graph_text({"nodes": [], "edges": []}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
