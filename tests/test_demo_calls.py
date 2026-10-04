import unittest
from backend.scripts.demo_calls import replay, reset


class FakeClient:
    def __init__(self):
        self.tables = {"profiles": [{"id": "senior", "role": "senior", "guardian_id": "guardian"}], "calls": [], "call_transcripts": [], "alerts": []}

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.operation, self.payload = "select", None
    def select(self, *_): return self
    def limit(self, *_): return self
    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self
    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self
    def like(self, key, _pattern):
        self.filters.append(lambda row: row.get(key, "").startswith("DEMO_"))
        return self
    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self
    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self
    def execute(self):
        rows = self.db.tables[self.table]
        matched = [r for r in rows if all(f(r) for f in self.filters)]
        if self.operation == "insert":
            row = {"id": str(len(rows)), **self.payload}
            rows.append(row); matched = [row]
        elif self.operation == "update":
            for row in matched: row.update(self.payload)
        return type("Result", (), {"data": matched})()


class DemoTests(unittest.TestCase):
    def test_replay_completes_and_has_one_alert(self):
        db = FakeClient()
        sid = replay(db, "senior", sleep=lambda _: None)
        self.assertTrue(sid.startswith("DEMO_"))
        self.assertEqual(db.tables["calls"][0]["status"], "completed")
        self.assertEqual(len(db.tables["alerts"]), 1)
        self.assertEqual(len(db.tables["call_transcripts"]), 4)

    def test_reset_excludes_real_other_senior_and_finished_calls(self):
        db = FakeClient()
        db.tables["calls"] = [
            {"id": "1", "call_sid": "CA_real", "senior_id": "senior", "status": "ringing"},
            {"id": "2", "call_sid": "DEMO_old", "senior_id": "senior", "status": "in_progress"},
            {"id": "3", "call_sid": "DEMO_other", "senior_id": "other", "status": "ringing"},
            {"id": "4", "call_sid": "DEMO_done", "senior_id": "senior", "status": "completed"},
        ]
        self.assertEqual(reset(db, "senior", dry_run=True), 1)
        self.assertEqual(db.tables["calls"][1]["status"], "in_progress")
        self.assertEqual(reset(db, "senior"), 1)
        self.assertEqual([r["status"] for r in db.tables["calls"]], ["ringing", "completed", "ringing", "completed"])

    def test_interruption_finishes_simulated_call(self):
        db = FakeClient()
        def interrupt(_): raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt): replay(db, "senior", sleep=interrupt)
        self.assertEqual(db.tables["calls"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
