"""Watch-mode diffing and Docker port attribution."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from portdeck import containers, watch
from portdeck.live import Listener
from portdeck.registry import Entry, Registry

DOCKER_PS = "\n".join([
    "a1b2c3\tbilling-db\tpostgres:16\t0.0.0.0:5433->5432/tcp, :::5433->5432/tcp",
    "d4e5f6\tcache\tredis:7\t127.0.0.1:6380->6379/tcp",
    "999999\tinternal\tbusybox\t9000/tcp",
])


class WatchTest(unittest.TestCase):
    def test_new_port_is_an_up_event(self) -> None:
        events = watch.diff({}, {5000: Listener(5000, 1, "node")}, {5000: "api"})
        self.assertEqual([(e.kind, e.port, e.project) for e in events],
                         [("up", 5000, "api")])

    def test_gone_port_is_a_down_event(self) -> None:
        events = watch.diff({5000: Listener(5000, 1, "node")}, {})
        self.assertEqual(events[0].kind, "down")

    def test_same_pid_is_not_an_event(self) -> None:
        before = {5000: Listener(5000, 1, "node")}
        self.assertEqual(watch.diff(before, dict(before)), [])

    def test_new_pid_on_the_same_port_is_a_replacement(self) -> None:
        events = watch.diff({5000: Listener(5000, 1, "node")},
                            {5000: Listener(5000, 2, "python")})
        self.assertEqual(events[0].kind, "replaced")
        self.assertEqual(events[0].pid, 2)

    def test_unregistered_ports_are_labelled(self) -> None:
        events = watch.diff({}, {7777: Listener(7777, 3, "go")})
        self.assertIn("unregistered", watch.format_event(events[0]))

    def test_run_emits_events_for_bounded_rounds(self) -> None:
        seen = []
        looks = [{}, {5000: Listener(5000, 1, "node")}]
        with mock.patch.object(watch.live, "listening_ports", side_effect=looks), \
             mock.patch.object(watch.time, "sleep"), redirect_stdout(io.StringIO()):
            code = watch.run(Registry([Entry("api", 5000)], ""), 0, seen.append, rounds=1)
        self.assertEqual(code, 0)
        self.assertEqual([(e.kind, e.project) for e in seen], [("up", "api")])

    def test_run_stops_on_interrupt(self) -> None:
        with mock.patch.object(watch.live, "listening_ports", return_value={}), \
             mock.patch.object(watch.time, "sleep", side_effect=KeyboardInterrupt), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(watch.run(Registry([], ""), 0, rounds=5), 0)


class ContainerTest(unittest.TestCase):
    def test_published_ports_map_to_containers(self) -> None:
        found = containers.parse(DOCKER_PS)
        self.assertEqual(found[5433].name, "billing-db")
        self.assertEqual(found[5433].image, "postgres:16")
        self.assertEqual(found[6380].name, "cache")

    def test_unpublished_ports_are_ignored(self) -> None:
        self.assertNotIn(9000, containers.parse(DOCKER_PS))

    def test_duplicate_bindings_keep_one_container(self) -> None:
        self.assertEqual(len(containers.parse(DOCKER_PS)), 2)

    def test_garbage_lines_are_skipped(self) -> None:
        self.assertEqual(containers.parse("not\ttab\tseparated\nx"), {})

    def test_host_ports_reads_both_binding_forms(self) -> None:
        spec = "0.0.0.0:8081->80/tcp, 127.0.0.1:8082->80/tcp, 90/tcp"
        self.assertEqual(sorted(containers.host_ports(spec)), [8081, 8082])

    def test_no_docker_means_no_containers(self) -> None:
        with mock.patch.object(containers, "_docker_binary", return_value=None):
            self.assertEqual(containers.by_port(), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
