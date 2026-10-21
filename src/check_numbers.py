"""
Check that the dashboard's numbers are correct.

For a few filter cases, this script calculates the KPI numbers in two
completely separate ways and checks that they agree:

  1. "Dashboard": the same functions the dashboard uses
     (filter_flights + compute_kpis from app.py, on the cleaned Parquet file).
  2. "By hand": plain pandas on the ORIGINAL raw CSV, without any of our code.

If both ways give the same answer, our cleaning and filtering did not
change or lose anything.

Run it from the project folder (after data_prep.py):
    python src/check_numbers.py
"""

import math
from pathlib import Path

import pandas as pd

# Importing app.py loads the cleaned data, but does not start the web server
# (that only happens when app.py itself is run).
from app import FLIGHTS, ON_TIME_LIMIT, compute_kpis, filter_flights

RAW_CSV = Path(__file__).resolve().parent.parent / "data" / "flights.csv"

# Each test case is written twice: once the way the dashboard's filters
# receive it, and once as a plain pandas condition on the raw CSV.
# (The raw CSV uses airline codes like "UA"; the dashboard uses full names.)
CASES = [
    {
        "name": "No filters (whole year)",
        "filters": dict(),
        "raw_condition": lambda raw: raw["year"] == 2013,
    },
    {
        "name": "July, United Airlines only",
        "filters": dict(start_date="2013-07-01", end_date="2013-07-31",
                        airlines=["United Air Lines Inc."]),
        "raw_condition": lambda raw: (raw["month"] == 7) & (raw["carrier"] == "UA"),
    },
    {
        "name": "To ATL or ORD, on Delta or American",
        "filters": dict(destinations=["ATL", "ORD"],
                        airlines=["Delta Air Lines Inc.", "American Airlines Inc."]),
        "raw_condition": lambda raw: raw["dest"].isin(["ATL", "ORD"])
                                     & raw["carrier"].isin(["DL", "AA"]),
    },
    {
        "name": "One day: 8 February (snowstorm)",
        "filters": dict(start_date="2013-02-08", end_date="2013-02-08"),
        "raw_condition": lambda raw: (raw["month"] == 2) & (raw["day"] == 8),
    },
]


def kpis_by_hand(raw_flights):
    """Calculate the four KPI numbers directly from raw CSV rows."""
    # In the raw data, a cancelled flight has no departure time,
    # and only flights that arrived have an arrival delay.
    arrived_delays = raw_flights["arr_delay"].dropna()
    return {
        "total_flights": len(raw_flights),
        "avg_delay": arrived_delays.mean(),
        "pct_delayed": (arrived_delays > ON_TIME_LIMIT).mean() * 100,
        "pct_cancelled": raw_flights["dep_time"].isna().mean() * 100,
    }


def numbers_match(a, b):
    """True if two numbers are equal (allowing for tiny rounding differences)."""
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def main():
    raw = pd.read_csv(RAW_CSV)
    failures = 0

    for case in CASES:
        print(f"\n{case['name']}")
        dashboard = compute_kpis(filter_flights(FLIGHTS, **case["filters"]))
        by_hand = kpis_by_hand(raw[case["raw_condition"](raw)])

        for kpi in ["total_flights", "avg_delay", "pct_delayed", "pct_cancelled"]:
            ok = numbers_match(dashboard[kpi], by_hand[kpi])
            if not ok:
                failures += 1
            result = "PASS" if ok else "FAIL"
            # Flight counts are whole numbers; the others get 2 decimals.
            number_format = ",.0f" if kpi == "total_flights" else ",.2f"
            print(f"  {result}  {kpi:<14} dashboard = {dashboard[kpi]:>8{number_format}}"
                  f"   by hand = {by_hand[kpi]:>8{number_format}}")

    print()
    if failures == 0:
        print("All checks passed.")
    else:
        print(f"{failures} check(s) FAILED.")
        raise SystemExit(1)  # a non-zero exit code tells other tools "something went wrong"


if __name__ == "__main__":
    main()
