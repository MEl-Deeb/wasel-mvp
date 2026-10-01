import csv
import tempfile
import unittest
from pathlib import Path

from wasel.core import DEFAULT_CSV, WaselService


class WaselServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        self.service = WaselService(self.db)
        self.service.reset(DEFAULT_CSV)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_finds_address_and_duplicate_risks(self):
        results = {item.order_id: item for item in self.service.scan()}
        self.assertEqual(results["WSL-1002"].status, "address_needed")
        self.assertIn("incomplete_address", results["WSL-1002"].issues)
        self.assertEqual(results["WSL-1004"].duplicate_of, "WSL-1003")
        self.assertEqual(results["WSL-1004"].status, "needs_review")

    def test_address_then_confirmation_tracks_impact(self):
        self.service.scan()
        self.service.update_address(
            "WSL-1002",
            "14 Makram Ebeid St, Nasr City",
            "City Centre",
        )
        updated = self.service.confirm("WSL-1002")
        self.assertEqual(updated["status"], "confirmed")
        metrics = self.service.metrics()
        self.assertEqual(metrics["revenue_protected_egp"], 1250)
        self.assertEqual(metrics["minutes_saved"], 10)

    def test_failed_delivery_can_be_rescheduled(self):
        self.service.scan()
        updated = self.service.reschedule("WSL-1006", "2026-10-02", "18:00-21:00")
        self.assertEqual(updated["status"], "rescheduled")
        metrics = self.service.metrics()
        self.assertEqual(metrics["recovered_revenue_egp"], 760)
        self.assertEqual(metrics["avoided_cost_egp"], 60)

    def test_invalid_short_address_is_rejected(self):
        self.service.scan()
        with self.assertRaises(ValueError):
            self.service.update_address("WSL-1002", "Maadi", "Mall")

    def test_custom_csv_import(self):
        custom = Path(self.temp.name) / "custom.csv"
        with DEFAULT_CSV.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))[:1]
        with custom.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        service = WaselService(Path(self.temp.name) / "custom.db")
        self.assertEqual(service.import_csv(custom), 1)
        self.assertEqual(len(service.list_orders()), 1)


if __name__ == "__main__":
    unittest.main()
