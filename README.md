# CallSieve spam list

A daily list of phone numbers that several different people have reported to
the US Federal Trade Commission as unwanted callers. The CallSieve Android app
downloads `spamlist.txt` from this repository.

- **Source:** [FTC Do Not Call Reported Calls Data](https://www.ftc.gov/policy-notices/open-government/data-sets/do-not-call-data), published each weekday.
- **Window:** the last 30 days of reports.
- **Floor:** a number is listed only when reports came from at least 3 different places.
- **Format:** `number,distinct_reports`, one per line, most reported first. Lines starting with `#` are comments.

The FTC states that none of these reports are verified, and callers often fake
their numbers. A listing means "reported by several people", not "proven spam".
Numbers drop off on their own once reports stop for 30 days.

`build_spam_list.py` builds the list; the workflow in `.github/workflows` runs
it on weekdays. No personal data is collected: the app only downloads this file.
