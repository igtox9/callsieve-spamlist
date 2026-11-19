#!/usr/bin/env python3
"""Build CallSieve's known-spam list from the FTC's Do Not Call reported calls data.

Data comes from the FTC's official developer API:
https://www.ftc.gov/developer/api/v0/endpoints/do-not-call-dnc-reported-calls-data-api
(The FTC website's CSV files refuse automated downloads; the API is the
supported route.) A free key from https://api.data.gov/signup is required and
is read from the FTC_API_KEY environment variable.

Each run:
  1. Downloads any days in the last WINDOW_DAYS that are not yet in the local
     cache folder (newest first), staying inside the API's hourly rate limit.
     A day that does not fit is picked up by a later run.
  2. Counts how many DIFFERENT people reported each number across the cache.
  3. Writes spamlist.txt with one "number,count" line per number that reaches
     MIN_REPORTS.

The FTC states that none of the reports are verified, and callers often fake
their number, so a single report means little. That is why the list only
includes numbers reported from several different places.

Uses only the Python standard library.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WINDOW_DAYS = 30
MIN_REPORTS = 3        # floor: fewer distinct reporters than this is never published
MIN_DAYS_TO_PUBLISH = 5
PAGE_SIZE = 50         # the API's maximum
MAX_PAGES_PER_DAY = 2000
RECENT_DAYS = 4        # an empty recent day may simply not be posted yet
API = "https://api.ftc.gov/v0/dnc-complaints"
USER_AGENT = "CallSieve-spamlist/1.0 (+https://github.com/igtox9/callsieve-spamlist)"


class OutOfBudget(Exception):
    """The hourly API allowance is used up; stop and let a later run continue."""


def clean_number(raw):
    """Return a 10-digit US/Canada number, or None if it is not a usable one."""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
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


def reporter_key(attrs):
    """The data has no reporter ID. City + state + area code is the closest
    stand-in, so one person reporting a number repeatedly counts once."""
    parts = [
        str(attrs.get("consumer-city") or "").strip().lower(),
        str(attrs.get("consumer-state") or "").strip().lower(),
        str(attrs.get("consumer-area-code") or "").strip(),
    ]
    key = "|".join(p.replace("|", " ").replace("\t", " ").replace("\n", " ") for p in parts)
    if key == "||":
        # No location at all: treat each such report as its own reporter.
        key = "seq:" + str(attrs.get("seq") or attrs.get("created-date") or "")
    return key


def rows_from_records(records):
    """Turn one API page into (number, reporter_key) pairs, skipping junk."""
    rows = []
    for record in records or []:
        attrs = record.get("attributes") if isinstance(record, dict) else None
        if not isinstance(attrs, dict):
            continue
        number = clean_number(attrs.get("company-phone-number"))
        if number is None:
            continue
        rows.append((number, reporter_key(attrs)))
    return rows


def count_reporters(day_rows):
    """day_rows: iterable of lists of (number, reporter_key). Returns {number: count}."""
    reporters = {}
    for rows in day_rows:
        for number, who in rows:
            reporters.setdefault(number, set()).add(who)
    return {n: len(r) for n, r in reporters.items()}


def build_lines(counts, today, days_used, min_reports=MIN_REPORTS):
    kept = {n: c for n, c in counts.items() if c >= min_reports}
    lines = [
        "# CallSieve known-spam list, format 1: number,distinct_reports",
        "# Source: FTC Do Not Call Reported Calls Data (public, unverified reports)",
        f"# generated={today.isoformat()} window_days={WINDOW_DAYS} days_used={days_used} "
        f"min_reports={min_reports} numbers={len(kept)}",
    ]
    for number in sorted(kept, key=lambda n: (-kept[n], n)):
        lines.append(f"{number},{kept[number]}")
    return lines


# ---------------------------------------------------------------- cache files

def cache_path(cache_dir, day):
    return os.path.join(cache_dir, f"{day.isoformat()}.tsv")


def write_day(cache_dir, day, rows):
    tmp = cache_path(cache_dir, day) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for number, who in sorted(set(rows)):
            f.write(f"{number}\t{who}\n")
    os.replace(tmp, cache_path(cache_dir, day))


def read_day(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            number, sep, who = line.rstrip("\n").partition("\t")
            if sep and clean_number(number) == number:
                rows.append((number, who))
    return rows


def prune_cache(cache_dir, oldest):
    for name in os.listdir(cache_dir):
        try:
            day = dt.date.fromisoformat(name.split(".")[0])
        except ValueError:
            continue
        if day < oldest or name.endswith(".tmp"):
            os.remove(os.path.join(cache_dir, name))


# ------------------------------------------------------------------- API calls

class Api:
    def __init__(self, key, reserve=5, max_requests=950):
        self.key = key
        self.reserve = reserve
        self.left = max_requests
        self.requests = 0

    def page(self, day, offset):
        if self.left <= 0:
            raise OutOfBudget()
        query = urllib.parse.urlencode({
            "created_date": f'"{day.isoformat()}"',
            "items_per_page": PAGE_SIZE,
            "offset": offset,
            "sort_order": "ASC",
        })
        req = urllib.request.Request(
            f"{API}?{query}",
            headers={"X-Api-Key": self.key, "User-Agent": USER_AGENT},
        )
        for attempt in range(3):
            try:
                self.left -= 1
                self.requests += 1
                with urllib.request.urlopen(req, timeout=60) as resp:
                    remaining = resp.headers.get("X-RateLimit-Remaining")
                    if remaining is not None and remaining.isdigit():
                        self.left = min(self.left, int(remaining) - self.reserve)
                    body = json.loads(resp.read().decode("utf-8", errors="replace"))
                    data = body.get("data") if isinstance(body, dict) else None
                    return data if isinstance(data, list) else []
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    raise OutOfBudget()
                if e.code == 403:
                    raise SystemExit("The FTC API rejected the key (HTTP 403). Check FTC_API_KEY.")
                if attempt == 2:
                    raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt == 2:
                    raise
            time.sleep(3 * (attempt + 1))
        return []

    def day(self, day):
        """All usable rows for one day. Raises OutOfBudget if it cannot finish."""
        rows, offset = [], 0
        for _ in range(MAX_PAGES_PER_DAY):
            data = self.page(day, offset)
            rows.extend(rows_from_records(data))
            if len(data) < PAGE_SIZE:
                return rows, offset + len(data)
            offset += PAGE_SIZE
        return rows, offset


def main(out_path="spamlist.txt", cache_dir="daily"):
    key = os.environ.get("FTC_API_KEY", "").strip()
    if not key:
        print("FTC_API_KEY is not set. Get a free key at https://api.data.gov/signup "
              "and add it as a repository secret named FTC_API_KEY.", file=sys.stderr)
        return 2

    os.makedirs(cache_dir, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date()
    oldest = today - dt.timedelta(days=WINDOW_DAYS)
    prune_cache(cache_dir, oldest)

    api = Api(key)
    try:
        # Yesterday backwards: today's reports are not complete yet.
        for back in range(1, WINDOW_DAYS + 1):
            day = today - dt.timedelta(days=back)
            if os.path.exists(cache_path(cache_dir, day)):
                continue
            rows, total = api.day(day)
            if total == 0 and back <= RECENT_DAYS:
                print(f"{day}: nothing posted yet, will retry")
                continue
            write_day(cache_dir, day, rows)
            print(f"{day}: {total} reports, {len(rows)} usable")
    except OutOfBudget:
        print(f"Hourly API allowance used after {api.requests} requests; "
              "a later run will fetch the remaining days.")
    except Exception as e:  # keep what was fetched; publish from the cache
        print(f"Stopped early after {api.requests} requests: {e}", file=sys.stderr)

    files = sorted(n for n in os.listdir(cache_dir) if n.endswith(".tsv"))
    non_empty = [n for n in files if os.path.getsize(os.path.join(cache_dir, n)) > 0]
    print(f"Cache holds {len(files)} days ({len(non_empty)} with reports).")
    if len(non_empty) < MIN_DAYS_TO_PUBLISH:
        print(f"Fewer than {MIN_DAYS_TO_PUBLISH} days cached; not writing a list yet.")
        return 0
    counts = count_reporters(read_day(os.path.join(cache_dir, n)) for n in files)
    lines = build_lines(counts, today, len(non_empty))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {len(lines) - 3} numbers to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
