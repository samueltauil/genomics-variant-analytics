"""Tests for scripts/reset_demo.py (OpenSpec task 11.9).

Populates the real local stores via scripts.rehearse_demo_failures, then
verifies diagnosis, reset, idempotency, an injected (partial) interruption,
and that reset never touches anything outside its explicitly named files and
directories.
"""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.rehearse_demo_failures import rehearse_all
from scripts.reset_demo import diagnose, reset, STORE_DIRECTORIES, STORE_FILES


class ResetDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_root = Path(self.temporary.name)

    def test_diagnose_on_an_empty_state_root_is_clean(self):
        report = diagnose(self.state_root)
        self.assertTrue(report["clean"])
        self.assertFalse(report["infrastructure_touched"])
        self.assertTrue(all(store["clean"] for store in report["stores"]))
        self.assertTrue(all(directory["clean"] for directory in report["directories"]))

    def test_diagnose_reports_dirty_stores_and_directory_after_rehearsal(self):
        rehearse_all(self.state_root)

        report = diagnose(self.state_root)

        self.assertFalse(report["clean"])
        dirty = {store["name"] for store in report["stores"] if not store["clean"]}
        self.assertEqual(
            dirty,
            {"variant_store.sqlite3", "metadata_store.sqlite3", "landing_inventory.sqlite3",
             "run_history.sqlite3"},
        )
        directory = next(
            entry for entry in report["directories"] if entry["name"] == "rehearsal-landing"
        )
        self.assertFalse(directory["clean"])
        self.assertGreater(directory["file_count"], 0)

    def test_reset_returns_environment_to_a_clean_starting_state(self):
        rehearse_all(self.state_root)

        report = reset(self.state_root)

        self.assertTrue(report["clean"])
        self.assertFalse(report["infrastructure_touched"])
        self.assertCountEqual(
            report["removed"],
            ["variant_store.sqlite3", "metadata_store.sqlite3",
             "landing_inventory.sqlite3", "run_history.sqlite3"],
        )
        self.assertEqual(report["removed_directories"], ["rehearsal-landing"])
        for name in STORE_FILES:
            self.assertFalse((self.state_root / name).exists())
        for name in STORE_DIRECTORIES:
            self.assertFalse((self.state_root / name).exists())

    def test_reset_is_idempotent_when_run_again_after_already_clean(self):
        rehearse_all(self.state_root)
        reset(self.state_root)

        second = reset(self.state_root)

        self.assertTrue(second["clean"])
        self.assertEqual(second["removed"], [])
        self.assertEqual(second["removed_directories"], [])

    def test_interrupted_reset_can_be_diagnosed_for_clean_versus_dirty_stores(self):
        """Simulate a reset interrupted after removing some, but not all, stores."""
        rehearse_all(self.state_root)

        # Inject an interruption: only the variant store and rehearsal landing
        # directory were removed before the process stopped.
        (self.state_root / "variant_store.sqlite3").unlink()

        mid_report = diagnose(self.state_root)
        by_name = {store["name"]: store for store in mid_report["stores"]}
        self.assertTrue(by_name["variant_store.sqlite3"]["clean"])
        self.assertFalse(by_name["variant_store.sqlite3"]["exists"])
        self.assertFalse(by_name["metadata_store.sqlite3"]["clean"])
        self.assertTrue(by_name["metadata_store.sqlite3"]["exists"])
        self.assertFalse(by_name["landing_inventory.sqlite3"]["clean"])
        self.assertFalse(mid_report["clean"])

        final = reset(self.state_root)

        self.assertTrue(final["clean"])
        self.assertNotIn("variant_store.sqlite3", final["removed"])
        self.assertIn("metadata_store.sqlite3", final["removed"])
        self.assertIn("landing_inventory.sqlite3", final["removed"])
        self.assertIn("run_history.sqlite3", final["removed"])

        self.assertTrue(diagnose(self.state_root)["clean"])

    def test_reset_never_deletes_anything_outside_its_named_files_and_directories(self):
        rehearse_all(self.state_root)
        unrelated_file = self.state_root / "unrelated.sqlite3"
        unrelated_file.write_text("keep-me")
        unrelated_directory = self.state_root / "unrelated-directory"
        unrelated_directory.mkdir()
        (unrelated_directory / "keep.txt").write_text("keep-me")
        sibling = self.state_root.parent / "sibling.sqlite3"
        sibling.write_text("keep-me")
        self.addCleanup(sibling.unlink)

        reset(self.state_root)

        self.assertTrue(unrelated_file.exists())
        self.assertEqual(unrelated_file.read_text(), "keep-me")
        self.assertTrue((unrelated_directory / "keep.txt").exists())
        self.assertTrue(sibling.exists())

    def test_reset_report_has_no_prior_delivery_rows_visible_in_any_store(self):
        rehearse_all(self.state_root)

        reset(self.state_root)

        for name in ("variant_store.sqlite3", "metadata_store.sqlite3",
                     "landing_inventory.sqlite3", "run_history.sqlite3"):
            self.assertFalse((self.state_root / name).exists())


if __name__ == "__main__":
    unittest.main()
