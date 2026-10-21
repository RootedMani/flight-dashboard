"""
Stage 3 - Data preparation.

Reads the raw CSV (read-only, it is never changed), cleans it, adds helpful
columns and saves the result as a Parquet file that the dashboard can load fast.

Run it from the project folder:
    python src/data_prep.py
"""

from pathlib import Path

import pandas as pd

# Build paths from this file's location, so the script works no matter
# which folder you run it from.
PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "flights.csv"
CLEAN_PARQUET = PROJECT_DIR / "data" / "clean_flights.parquet"

# Delay categories, based on ARRIVAL delay in minutes.
# 15 minutes is the official US (FAA) limit for a flight to count as "on time".
# pd.cut puts a value in the bin (low, high], so e.g. 15 -> "On time", 16 -> "Small delay".
DELAY_BINS = [-float("inf"), 15, 45, 120, float("inf")]
DELAY_LABELS = ["On time", "Small delay", "Medium delay", "Large delay"]
ON_TIME_LIMIT = 15

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_raw_data(path):
    """Read the original CSV file into a DataFrame."""
    return pd.read_csv(path)


def add_status_flags(df):
    """Mark cancelled and diverted flights.

    We KEEP these rows (they are real flights that were planned), but we need
    to know about them because they have no delay value.
    """
    # No departure time at all -> the plane never took off.
    df["cancelled"] = df["dep_time"].isna()
    # Took off, but has no arrival delay -> it landed somewhere else (diverted).
    df["diverted"] = df["dep_time"].notna() & df["arr_delay"].isna()
    return df


def handle_missing_values(df):
    """Deal with empty cells, one column at a time.

    dep_time, dep_delay, arr_time, arr_delay, air_time:
        Left EMPTY on purpose. They are only missing for cancelled/diverted
        flights. Filling them with 0 would pretend those flights were perfectly
        on time and would make the average delay look better than it really is.
        pandas automatically skips empty values when calculating a mean.

    tailnum (the plane's registration number):
        Filled with "Unknown". It is only missing for cancelled flights
        (no plane was assigned), and it is just a text label, so filling it
        cannot distort any numbers.
    """
    df["tailnum"] = df["tailnum"].fillna("Unknown")
    return df


def convert_datetimes(df):
    """Turn the date/time columns into real datetime values.

    The raw times are stored as HHMM numbers (1453 means 14:53), which
    pandas cannot do maths with. We build proper datetimes instead.
    """
    # The calendar date of the flight.
    df["flight_date"] = pd.to_datetime(df[["year", "month", "day"]])

    # Scheduled departure = date + scheduled hour + scheduled minute.
    df["sched_dep_datetime"] = (
        df["flight_date"]
        + pd.to_timedelta(df["hour"], unit="h")
        + pd.to_timedelta(df["minute"], unit="min")
    )

    # Actual departure = scheduled departure + departure delay.
    # Adding the delay (instead of reading dep_time) handles flights that
    # left after midnight, and the strange "2400" value, correctly.
    # Cancelled flights get NaT ("Not a Time"), the datetime version of empty.
    df["dep_datetime"] = df["sched_dep_datetime"] + pd.to_timedelta(df["dep_delay"], unit="min")

    # We do NOT build arrival datetimes: arrival times are in the destination's
    # local time zone (e.g. Los Angeles is 3 hours behind New York), so mixing
    # them with New York departure times would give wrong results.

    # time_hour is just the scheduled departure rounded to the hour, stored as
    # text. sched_dep_datetime replaces it, so we remove it.
    df = df.drop(columns=["time_hour"])
    return df


def add_helper_columns(df):
    """Add columns that make analysis and filtering easier."""
    # "name" is too vague, so we rename it to say what it holds.
    df = df.rename(columns={"name": "airline"})

    # year and month already exist in the raw data; we add the weekday.
    # An ordered category keeps Monday..Sunday in the right order in charts.
    df["day_of_week"] = pd.Categorical(
        df["flight_date"].dt.day_name(), categories=DAY_ORDER, ordered=True
    )

    # A readable flight number like "UA1545" (a number alone repeats across airlines).
    df["flight_code"] = df["carrier"] + df["flight"].astype(str)

    # True/False: did the flight arrive more than 15 minutes late?
    # Stays empty for cancelled/diverted flights, so they don't count either way.
    # "boolean" (lower-case b) is pandas' True/False type that also allows empty values.
    is_delayed = (df["arr_delay"] > ON_TIME_LIMIT).astype("boolean")
    df["is_delayed"] = is_delayed.mask(df["arr_delay"].isna())
    return df


def add_delay_category(df):
    """Sort every flight into a delay group based on its arrival delay."""
    category = pd.cut(df["arr_delay"], bins=DELAY_BINS, labels=DELAY_LABELS)

    # Flights without an arrival delay get their own groups, so they don't
    # silently disappear or get mistaken for "On time".
    category = category.cat.add_categories(["Diverted", "Cancelled"])
    category[df["diverted"]] = "Diverted"
    category[df["cancelled"]] = "Cancelled"

    df["delay_category"] = category
    return df


def shrink_text_columns(df):
    """Store repeated text as 'category' type.

    A column like 'origin' only has 3 different values repeated 336,776 times.
    The category type stores each value once, which makes the file smaller and
    filtering in the dashboard faster.
    """
    for column in ["carrier", "airline", "origin", "dest"]:
        df[column] = df[column].astype("category")
    return df


def print_report(raw, clean):
    """Print a short summary of what changed."""
    print("=" * 60)
    print("DATA PREPARATION REPORT")
    print("=" * 60)
    print(f"Rows before: {len(raw):,}   Rows after: {len(clean):,}   (no rows dropped)")
    print(f"Columns before: {raw.shape[1]}   Columns after: {clean.shape[1]}")

    added = [c for c in clean.columns if c not in raw.columns]
    removed = [c for c in raw.columns if c not in clean.columns]
    print(f"\nAdded columns:   {', '.join(added)}")
    print(f"Removed/renamed: {', '.join(removed)}  (time_hour -> sched_dep_datetime, name -> airline)")

    print(f"\nCancelled flights: {clean['cancelled'].sum():,}")
    print(f"Diverted flights:  {clean['diverted'].sum():,}")
    print(f"tailnum filled with 'Unknown': {raw['tailnum'].isna().sum():,}")

    print("\nDelay categories (arrival delay):")
    counts = clean["delay_category"].value_counts(sort=False)
    for label, count in counts.items():
        print(f"  {label:<13} {count:>8,}  ({count / len(clean):.1%})")

    still_missing = clean.isna().sum()
    still_missing = still_missing[still_missing > 0]
    print("\nColumns that are still empty for some rows (on purpose, see comments):")
    for column, count in still_missing.items():
        print(f"  {column:<13} {count:>8,}")

    size_mb = CLEAN_PARQUET.stat().st_size / 1_000_000
    print(f"\nSaved {CLEAN_PARQUET.relative_to(PROJECT_DIR)} ({size_mb:.1f} MB)")


def main():
    raw = load_raw_data(RAW_CSV)

    # Work on a copy so `raw` stays as it was, for the before/after report.
    df = raw.copy()
    df = add_status_flags(df)
    df = handle_missing_values(df)
    df = convert_datetimes(df)
    df = add_helper_columns(df)
    df = add_delay_category(df)
    df = shrink_text_columns(df)

    # Safety check: cleaning must never lose or duplicate flights.
    assert len(df) == len(raw), "Row count changed during cleaning!"

    df.to_parquet(CLEAN_PARQUET, index=False)
    print_report(raw, df)


if __name__ == "__main__":
    main()
