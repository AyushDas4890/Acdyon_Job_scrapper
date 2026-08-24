"""
test_ingester.py — basic unit tests for the ingestion pipeline's pure logic.

Run with: python -m unittest test_ingester -v

Covers the two places most likely to break silently: field normalization
(normalize_hn_item) and the dedup-on-load logic (load_existing_jobs). Network
calls are not exercised here — fetch_with_retry is a thin wrapper around
`requests` and is better covered by an integration/mocked-transport test if
this pipeline grows.
"""

import json
import os
import tempfile
import unittest

import ingester


class TestNormalizeHnItem(unittest.TestCase):
    def test_valid_item_normalizes(self):
        raw = {"id": 1, "title": "Senior Engineer", "by": "alice", "time": 1700000000}
        listing = ingester.normalize_hn_item(raw)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.id, 1)
        self.assertEqual(listing.title, "Senior Engineer")
        self.assertEqual(listing.posted_by, "alice")
        self.assertIsNone(listing.company)

    def test_missing_required_field_returns_none(self):
        raw = {"id": 2, "title": "Engineer", "by": "bob"}  # no "time"
        self.assertIsNone(ingester.normalize_hn_item(raw))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(ingester.normalize_hn_item({}))

    def test_company_parsed_from_pipe_separator(self):
        raw = {"id": 3, "title": "Backend Engineer | Acme Corp", "by": "carol", "time": 1700000000}
        listing = ingester.normalize_hn_item(raw)
        self.assertEqual(listing.company, "Acme Corp")

    def test_company_parsed_from_parens(self):
        raw = {"id": 4, "title": "Senior Engineer (Acme Corp)", "by": "dave", "time": 1700000000}
        listing = ingester.normalize_hn_item(raw)
        self.assertEqual(listing.company, "Acme Corp")

    def test_no_company_pattern_leaves_none(self):
        raw = {"id": 5, "title": "Plain Title With No Company", "by": "erin", "time": 1700000000}
        listing = ingester.normalize_hn_item(raw)
        self.assertIsNone(listing.company)

    def test_posted_at_iso_is_derived_from_unix_time(self):
        raw = {"id": 6, "title": "X", "by": "frank", "time": 1700000000}
        listing = ingester.normalize_hn_item(raw)
        self.assertTrue(listing.posted_at_iso.endswith("Z"))


class TestLoadExistingJobs(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_data_file = ingester.DATA_FILE
        ingester.DATA_FILE = os.path.join(self._tmpdir.name, "jobs.json")

    def tearDown(self):
        ingester.DATA_FILE = self._orig_data_file
        self._tmpdir.cleanup()

    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(ingester.load_existing_jobs(), {})

    def test_malformed_json_returns_empty_dict(self):
        with open(ingester.DATA_FILE, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertEqual(ingester.load_existing_jobs(), {})

    def test_loads_and_keys_by_id(self):
        payload = {"jobs": [{"id": 10, "title": "A"}, {"id": 11, "title": "B"}]}
        with open(ingester.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        loaded = ingester.load_existing_jobs()
        self.assertEqual(set(loaded.keys()), {10, 11})
        self.assertEqual(loaded[10]["title"], "A")

    def test_jobs_missing_id_are_skipped(self):
        payload = {"jobs": [{"id": 20, "title": "A"}, {"title": "no id"}]}
        with open(ingester.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        loaded = ingester.load_existing_jobs()
        self.assertEqual(set(loaded.keys()), {20})


if __name__ == "__main__":
    unittest.main()
