import datetime as dt
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_spam_list as b

HEADER = "Company_Phone_Number,Created_Date,Violation_Date,Consumer_City,Consumer_State,Consumer_Area_Code,Subject,Recorded_Message_Or_Robocall\n"

def row(num, city, state="Texas", area="817"):
    return f'{num},2026-11-16 00:08:24,2026-11-13 11:57:00,{city},{state},{area},"Calls pretending to be government, businesses, or family and friends",Y\n'

class BuildTest(unittest.TestCase):
    def test_clean_number(self):
        self.assertEqual(b.clean_number("6014833411"), "6014833411")
        self.assertEqual(b.clean_number("1-601-483-3411"), "6014833411")
        self.assertIsNone(b.clean_number("12345"))
        self.assertIsNone(b.clean_number("0014833411"))   # bad area code
        self.assertIsNone(b.clean_number("6011833411"))   # bad exchange
        self.assertIsNone(b.clean_number("5555555555"))
        self.assertIsNone(b.clean_number(""))
        self.assertIsNone(b.clean_number(None))

    def test_distinct_reporters_and_floor(self):
        text = HEADER + row("6014833411", "Keller") + row("6014833411", "Keller") \
            + row("6014833411", "Dallas") + row("6014833411", "Austin") \
            + row("2282621203", "Keller") + row("2282621203", "Dallas")
        reporters = {}
        self.assertEqual(b.add_reports(text, reporters), 6)
        # Same city reporting twice counts once.
        self.assertEqual(len(reporters["6014833411"]), 3)
        lines = b.build_lines(reporters, dt.date(2026, 11, 19), 20)
        data = [l for l in lines if not l.startswith("#")]
        self.assertEqual(data, ["6014833411,3"])  # 2 reporters is under the floor

    def test_counts_add_across_days_and_sort(self):
        reporters = {}
        b.add_reports(HEADER + "".join(row("8176238484", c) for c in "abcd"), reporters)
        b.add_reports(HEADER + "".join(row("8176238484", c) for c in "cdef")
                      + "".join(row("4692832023", c) for c in "abc"), reporters)
        data = [l for l in b.build_lines(reporters, dt.date(2026, 11, 19), 20) if not l.startswith("#")]
        self.assertEqual(data, ["8176238484,6", "4692832023,3"])

    def test_quoted_commas_and_junk_rows(self):
        text = HEADER + row("not a number", "Keller") + ",,,,,,,\n" + row("6014833411", "Keller")
        reporters = {}
        self.assertEqual(b.add_reports(text, reporters), 1)

if __name__ == "__main__":
    unittest.main()
