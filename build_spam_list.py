#!/usr/bin/env python3
"""Build CallSieve's known-spam list from the FTC's Do Not Call reported calls data.

The FTC publishes one CSV per weekday of the phone numbers people reported:
https://www.ftc.gov/policy-notices/open-government/data-sets/do-not-call-data

This script downloads the last WINDOW_DAYS of files, counts how many DIFFERENT
people reported each number, and writes spamlist.txt with one "number,count"
line per number that reaches MIN_REPORTS.

The FTC states that none of the reports are verified, and callers often fake
their number, so a single report means little. That is why the list only
includes numbers reported from several different places.

Uses only the Python standard library.
"""
import csv
import datetime as dt
import io
import sys
import urllib.error
import urllib.request

WINDOW_DAYS = 30
MIN_REPORTS = 3  # floor: fewer distinct reporters than this is never published
URL = "https://www.ftc.gov/sites/default/files/DNC_Complaint_Numbers_{date}.csv"
USER_AGENT = "CallSieve-spamlist/1.0 (+https://github.com/igtox9/callsieve-spamlist)"


def clean_number(raw):
    """Return a 10-digit US/Canada number, or None if it is not a usable one."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    # Area codes and exchanges never start with 0 or 1.
    if digits[0] in "01" or digits[3] in "01":
        return None
    if len(set(digits)) == 1:
        return None
    return digits


def add_reports(csv_text, reporters):
    """Add one day's CSV to reporters: {number: set of reporter keys}."""
    rows = csv.DictReader(io.StringIO(csv_text))
    added = 0
    for row in rows:
        number = clean_number(row.get("Company_Phone_Number"))
        if number is None:
            continue
        # The data has no reporter ID. City + state + area code is the closest
        # stand-in, so one person reporting a number repeatedly counts once.
        who = (
            (row.get("Consumer_City") or "").strip().lower(),
            (row.get("Consumer_State") or "").strip().lower(),
            (row.get("Consumer_Area_Code") or "").strip(),
        )
        if who == ("", "", ""):
            # No location at all: count each such row as its own reporter.
            who = ("row", str(len(reporters.get(number, ()))), row.get("Created_Date") or "")
        reporters.setdefault(number, set()).add(who)
        added += 1
    return added


def build_lines(reporters, today, days_used, min_reports=MIN_REPORTS):
    counts = {n: len(r) for n, r in reporters.items() if len(r) >= min_reports}
    lines = [
        "# CallSieve known-spam list, format 1: number,distinct_reports",
        "# Source: FTC Do Not Call Reported Calls Data (public, unverified reports)",
        f"# generated={today.isoformat()} window_days={WINDOW_DAYS} files_used={days_used} "
        f"min_reports={min_reports} numbers={len(counts)}",
    ]
    for number in sorted(counts, key=lambda n: (-counts[n], n)):
        lines.append(f"{number},{counts[number]}")
    return lines


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main(out_path="spamlist.txt"):
    today = dt.datetime.now(dt.timezone.utc).date()
    reporters, days_used = {}, 0
    for back in range(WINDOW_DAYS + 1):
        day = today - dt.timedelta(days=back)
        try:
            text = fetch(URL.format(date=day.isoformat()))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # weekends, holidays, or not published yet
                continue
            print(f"{day}: HTTP {e.code}", file=sys.stderr)
            continue
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"{day}: {e}", file=sys.stderr)
            continue
        if "Company_Phone_Number" not in text[:400]:
            print(f"{day}: unexpected file format, skipped", file=sys.stderr)
            continue
        rows = add_reports(text, reporters)
        days_used += 1
        print(f"{day}: {rows} reports")

    # Refuse to publish a suspiciously thin list (e.g. the FTC site was down),
    # so a bad run never replaces a good list.
    if days_used < 5:
        print(f"Only {days_used} daily files were available; not writing a list.", file=sys.stderr)
        return 1
    lines = build_lines(reporters, today, days_used)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {len(lines) - 3} numbers to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
