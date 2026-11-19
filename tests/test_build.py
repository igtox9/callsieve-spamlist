import datetime as dt
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_spam_list as b


def rec(num, city, state="Texas", area="817", seq=1):
    return {"type": "dnc_complaint", "id": "x", "attributes": {
        "company-phone-number": num, "created-date": "2026-11-17 14:52:41",
        "violation-date": "2026-11-17 12:46:00", "consumer-city": city,
        "consumer-state": state, "consumer-area-code": area,
        "subject": "Other", "recorded-message-or-robocall": "Y", "seq": seq}}


def data_lines(counts):
    return [l for l in b.build_lines(counts, dt.date(2026, 11, 19), 20) if not l.startswith("#")]


class BuildTest(unittest.TestCase):
    def test_clean_number(self):
        self.assertEqual(b.clean_number("6014833411"), "6014833411")
        self.assertEqual(b.clean_number("1-601-483-3411"), "6014833411")
        self.assertEqual(b.clean_number(6014833411), "6014833411")
        self.assertIsNone(b.clean_number("12345"))
        self.assertIsNone(b.clean_number("0014833411"))   # bad area code
        self.assertIsNone(b.clean_number("6011833411"))   # bad exchange
        self.assertIsNone(b.clean_number("5555555555"))
        self.assertIsNone(b.clean_number("06/10/2026"))   # seen in real API data
        self.assertIsNone(b.clean_number(""))
        self.assertIsNone(b.clean_number(None))

    def test_distinct_reporters_and_floor(self):
        rows = b.rows_from_records([
            rec("6014833411", "Keller"), rec("6014833411", "Keller"),
            rec("6014833411", "Dallas"), rec("6014833411", "Austin"),
            rec("2282621203", "Keller"), rec("2282621203", "Dallas"),
        ])
        self.assertEqual(len(rows), 6)
        counts = b.count_reporters([rows])
        self.assertEqual(counts["6014833411"], 3)      # same city twice counts once
        self.assertEqual(data_lines(counts), ["6014833411,3"])  # 2 is under the floor

    def test_counts_add_across_days_and_sort(self):
        day1 = b.rows_from_records([rec("8176238484", c) for c in "abcd"])
        day2 = b.rows_from_records([rec("8176238484", c) for c in "cdef"]
                                   + [rec("4692832023", c) for c in "abc"])
        self.assertEqual(data_lines(b.count_reporters([day1, day2])),
                         ["8176238484,6", "4692832023,3"])

    def test_junk_records_are_skipped(self):
        junk = [None, {}, {"attributes": None}, {"attributes": {"company-phone-number": "G"}},
                rec("not a number", "Keller")]
        self.assertEqual(b.rows_from_records(junk + [rec("6014833411", "Keller")]),
                         [("6014833411", "keller|texas|817")])
        self.assertEqual(b.rows_from_records(None), [])

    def test_missing_location_counts_each_report(self):
        rows = b.rows_from_records([rec("6014833411", "", "", "", seq=s) for s in (1, 2, 3)])
        self.assertEqual(b.count_reporters([rows])["6014833411"], 3)

    def test_cache_round_trip_and_prune(self):
        with tempfile.TemporaryDirectory() as d:
            day = dt.date(2026, 11, 17)
            rows = b.rows_from_records([rec("6014833411", "Kel\tler"), rec("6014833411", "Dallas")])
            b.write_day(d, day, rows)
            b.write_day(d, dt.date(2026, 10, 1), [])
            self.assertEqual(sorted(b.read_day(b.cache_path(d, day))), sorted(set(rows)))
            b.prune_cache(d, dt.date(2026, 10, 20))
            self.assertEqual(os.listdir(d), ["2026-11-17.tsv"])

    def test_partial_day_is_resumed_and_finished(self):
        day = dt.date(2026, 11, 17)
        pages = {0: [rec(f"601483{3000 + i}", f"c{i}") for i in range(50)],
                 50: [rec(f"601484{3000 + i}", f"c{i}") for i in range(50)],
                 100: [rec("6014853000", "last")]}

        class FakeApi(b.Api):
            def __init__(self, budget):
                super().__init__("k")
                self.budget = budget
            def page(self, d, offset):
                if self.budget <= 0:
                    raise b.OutOfBudget()
                self.budget -= 1
                return pages[offset]

        with tempfile.TemporaryDirectory() as d:
            progress = {"rows": [], "offset": 0}
            with self.assertRaises(b.OutOfBudget):
                FakeApi(2).day(day, progress)
            self.assertEqual(progress["offset"], 100)
            b.write_part(d, day, progress["rows"], progress["offset"])

            rows, offset = b.read_part(d, day)
            self.assertEqual((len(rows), offset), (100, 100))
            progress = {"rows": rows, "offset": offset}
            self.assertEqual(FakeApi(5).day(day, progress), 101)
            self.assertEqual(len(progress["rows"]), 101)
            # A damaged part file is ignored, never trusted.
            open(b.part_path(d, day), "w").write("#offset=37\n")
            self.assertEqual(b.read_part(d, day), ([], 0))
            self.assertEqual(b.read_part(d, dt.date(2026, 1, 1)), ([], 0))

    def test_no_key_exits_cleanly(self):
        old = os.environ.pop("FTC_API_KEY", None)
        try:
            self.assertEqual(b.main("unused.txt", "unused"), 2)
            self.assertFalse(os.path.exists("unused.txt"))
        finally:
            if old is not None:
                os.environ["FTC_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
