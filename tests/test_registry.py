"""Registry loading, saving, lookup and the shapes accepted on disk."""

import json
import os
import shutil
import tempfile
import unittest

from portdeck.registry import Entry, Registry, default_path


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="portdeck-reg-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "registry.json")

    def write(self, payload: object) -> str:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return self.path

    def test_loads_object_shape(self) -> None:
        self.write({"version": 1, "projects": [{"name": "a", "port": 5000}]})
        reg = Registry.load(self.path)
        self.assertEqual([e.name for e in reg.entries], ["a"])

    def test_loads_bare_list_shape(self) -> None:
        self.write([{"name": "a", "port": 5000, "path": "~/a"}])
        self.assertEqual(Registry.load(self.path).entries[0].port, 5000)

    def test_missing_file_is_an_empty_registry(self) -> None:
        reg = Registry.load(os.path.join(self.dir, "nope.json"))
        self.assertEqual(reg.entries, [])

    def test_broken_json_is_an_empty_registry(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(Registry.load(self.path).entries, [])

    def test_one_broken_record_does_not_drop_the_rest(self) -> None:
        self.write([{"name": "ok", "port": 5000}, {"name": "", "port": 1},
                    {"port": "abc"}, {"name": "also-ok", "port": 6000}])
        reg = Registry.load(self.path)
        self.assertEqual(sorted(e.name for e in reg.entries), ["also-ok", "ok"])

    def test_save_round_trip(self) -> None:
        reg = Registry([Entry("b", 6000, "~/b"), Entry("a", 5000, "~/a")], self.path)
        reg.save()
        again = Registry.load(self.path)
        self.assertEqual([(e.name, e.port) for e in again.sorted()],
                         [("a", 5000), ("b", 6000)])

    def test_upsert_by_name_updates_port(self) -> None:
        reg = Registry([Entry("a", 5000)], self.path)
        self.assertEqual(reg.upsert(Entry("a", 5001)), "updated")
        self.assertEqual(reg.entries[0].port, 5001)

    def test_upsert_same_values_is_unchanged(self) -> None:
        reg = Registry([Entry("a", 5000, "~/a")], self.path)
        self.assertEqual(reg.upsert(Entry("a", 5000, "~/a")), "unchanged")

    def test_upsert_new_entry_is_added(self) -> None:
        reg = Registry([], self.path)
        self.assertEqual(reg.upsert(Entry("new", 7000)), "added")
        self.assertEqual(len(reg.entries), 1)

    def test_by_port_groups_collisions(self) -> None:
        reg = Registry([Entry("a", 5000), Entry("b", 5000)], self.path)
        self.assertEqual(len(reg.by_port()[5000]), 2)

    def test_find_by_name_port_and_path(self) -> None:
        reg = Registry([Entry("alpha", 5000, self.dir)], self.path)
        self.assertIsNotNone(reg.find("alpha"))
        self.assertIsNotNone(reg.find("5000"))
        self.assertIsNotNone(reg.find(self.dir))
        self.assertIsNone(reg.find("nothing-like-this"))

    def test_find_by_unique_substring(self) -> None:
        reg = Registry([Entry("my-api-server", 5000)], self.path)
        self.assertEqual(reg.find("api").name, "my-api-server")

    def test_find_substring_is_ambiguous_with_two_matches(self) -> None:
        reg = Registry([Entry("api-one", 5000), Entry("api-two", 5001)], self.path)
        self.assertIsNone(reg.find("api"))

    def test_default_path_prefers_env_var(self) -> None:
        os.environ["PORTDECK_REGISTRY"] = self.path
        self.addCleanup(os.environ.pop, "PORTDECK_REGISTRY", None)
        self.assertEqual(default_path(), self.path)

    def test_default_path_uses_local_file(self) -> None:
        os.environ.pop("PORTDECK_REGISTRY", None)
        local = os.path.join(self.dir, "portdeck.json")
        self.write([])
        os.rename(self.path, local)
        self.assertEqual(default_path(self.dir), local)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
