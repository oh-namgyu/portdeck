"""Free-port suggestion."""

import unittest
from unittest import mock

from portdeck import allocate
from portdeck.live import Listener
from portdeck.registry import Entry, Registry


class AllocateTest(unittest.TestCase):
    def test_skips_registered_ports(self) -> None:
        reg = Registry([Entry("a", 4000), Entry("b", 4001)], "")
        self.assertEqual(allocate.free_ports(reg, 1, 4000, 4100, {}), [4002])

    def test_skips_live_ports(self) -> None:
        reg = Registry([], "")
        listeners = {4000: Listener(4000, 1, "x"), 4001: Listener(4001, 2, "y")}
        self.assertEqual(allocate.free_ports(reg, 1, 4000, 4100, listeners), [4002])

    def test_skips_ports_other_tools_grab(self) -> None:
        reg = Registry([], "")
        self.assertNotIn(8080, allocate.free_ports(reg, 5, 8078, 8100, {}))

    def test_returns_several(self) -> None:
        reg = Registry([Entry("a", 5001)], "")
        self.assertEqual(allocate.free_ports(reg, 3, 5000, 5100, {}), [5002, 5003, 5004])

    def test_exhausted_range_returns_what_it_found(self) -> None:
        reg = Registry([Entry("a", 4000)], "")
        self.assertEqual(allocate.free_ports(reg, 3, 4000, 4001, {}), [4001])

    def test_next_in_block_stays_in_the_hundred(self) -> None:
        reg = Registry([Entry("a", 6140), Entry("b", 6141)], "")
        self.assertEqual(allocate.next_in_block(reg, 6140, listeners={}), 6100)

    def test_next_in_block_returns_none_when_full(self) -> None:
        reg = Registry([Entry(str(p), p) for p in range(6100, 6200)], "")
        self.assertIsNone(allocate.next_in_block(reg, 6140, listeners={}))

    def test_suggest_near_a_project(self) -> None:
        reg = Registry([Entry("game", 6140, "")], "")
        with mock.patch.object(allocate.live, "listening_ports", return_value={}):
            self.assertEqual(list(allocate.suggest(reg, 1, near="game")), [6100])

    def test_suggest_ignores_unknown_project(self) -> None:
        reg = Registry([], "")
        with mock.patch.object(allocate.live, "listening_ports", return_value={}):
            ports = list(allocate.suggest(reg, 1, near="nope"))
        self.assertEqual(ports, [allocate.DEFAULT_RANGE[0]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
