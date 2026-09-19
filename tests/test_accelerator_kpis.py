import tempfile
import unittest
from pathlib import Path

from scripts.accelerator_kpis import (
    AcceleratorKpiCollector,
    KpiEventStore,
    run_local_synthetic_harness,
)
from scripts.variant_store import VariantStore


class AcceleratorKpiTests(unittest.TestCase):
    def test_local_synthetic_harness_derives_all_six_metrics_from_records(self):
        with tempfile.TemporaryDirectory() as directory:
            measurements = {item.name: item for item in run_local_synthetic_harness(directory)}

        self.assertEqual(
            set(measurements),
            {
                "pipeline_success_rate",
                "arrival_to_queryable_duration",
                "query_response_time",
                "records_linked_to_source_files",
                "reprocessing_time",
                "cost_per_sample",
            },
        )
        self.assertEqual(measurements["pipeline_success_rate"].value, 66.66666666666666)
        self.assertEqual(measurements["arrival_to_queryable_duration"].value, 540)
        self.assertGreaterEqual(measurements["query_response_time"].value, 0)
        self.assertEqual(measurements["records_linked_to_source_files"].value, 100)
        self.assertEqual(measurements["reprocessing_time"].value, 360)
        self.assertEqual(measurements["cost_per_sample"].value, 1.5)
        self.assertTrue(all(item.measurement_scope == "local synthetic measurement"
                            for item in measurements.values()))
        self.assertEqual(measurements["cost_per_sample"].source, "recorded counts or cost ledger")

    def test_collector_refuses_metrics_without_their_required_recorded_data(self):
        with tempfile.TemporaryDirectory() as directory:
            events = KpiEventStore(Path(directory) / "events.sqlite3")
            variants = VariantStore(Path(directory) / "variants.sqlite3")
            try:
                collector = AcceleratorKpiCollector(events, variants)

                with self.assertRaisesRegex(ValueError, "pipeline_success_rate"):
                    collector.pipeline_success_rate()
                with self.assertRaisesRegex(ValueError, "arrival_to_queryable_duration"):
                    collector.arrival_to_queryable_duration()
                with self.assertRaisesRegex(ValueError, "query_response_time"):
                    collector.query_response_time()
                with self.assertRaisesRegex(ValueError, "records_linked_to_source_files"):
                    collector.records_linked_to_source_files()
                with self.assertRaisesRegex(ValueError, "reprocessing_time"):
                    collector.reprocessing_time()
                with self.assertRaisesRegex(ValueError, "cost_per_sample"):
                    collector.cost_per_sample()
            finally:
                variants.close()
                events.close()


if __name__ == "__main__":
    unittest.main()
