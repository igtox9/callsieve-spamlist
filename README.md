# CallSieve spam list

A daily list of phone numbers that several different people have reported to
the US Federal Trade Commission as unwanted callers. The CallSieve Android app
downloads `spamlist.txt` from this repository.

- **Source:** [FTC Do Not Call Reported Calls Data](https://www.ftc.gov/policy-notices/open-government/data-sets/do-not-call-data), published each weekday and read through the [FTC developer API](https://www.ftc.gov/developer/api/v0/endpoints/do-not-call-dnc-reported-calls-data-api).
- **Window:** the 3 most recent days that have reports. The FTC posts a day of reports each weekday, usually a few days behind, so these are not always the last 3 calendar days.
- **Floor:** a number is listed only when reports came from at least 3 different places.
- **Number blocks:** a six-digit prefix (area code + exchange) is listed when at least 5 different numbers in it were reported by at least 8 different places. Callers who rotate numbers stay under the floor on each number, but the block stands out. The app treats unverified calls from a listed block as suspected spam.
- **Format:** `number,distinct_reports`, one per line, most reported first, then `prefix*,distinct_numbers` lines for number blocks. Lines starting with `#` are comments.

The FTC states that none of these reports are verified, and callers often fake
their numbers. A listing means "reported by several people", not "proven spam".
Numbers and blocks drop off on their own once they fall out of the 3-day window.

`build_spam_list.py` builds the list; the workflow in `.github/workflows` runs
it every few hours. It needs a free API key from https://api.data.gov/signup,
stored as a repository secret named `FTC_API_KEY`. No personal data is collected: the app only downloads this file.
