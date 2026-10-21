"""
Stage 4 - First analysis of the cleaned flight data.

The functions here each answer one question and return a small table.
The dashboard (app.py) reuses some of them, so the numbers in the printed
report and in the dashboard always come from the same code.

Run it from the project folder (after data_prep.py):
    python src/analysis.py
"""

import calendar
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
CLEAN_PARQUET = PROJECT_DIR / "data" / "clean_flights.parquet"


def load_clean_data(path=CLEAN_PARQUET):
    """Load the cleaned flights produced by data_prep.py."""
    return pd.read_parquet(path)


def flights_per_month(df):
    """Number of flights, cancellations and average arrival delay per month."""
    # observed=True: only show groups that actually exist in the data
    # (needed because some of our columns use the 'category' type).
    monthly = df.groupby("month", observed=True).agg(
        flights=("id", "count"),
        cancelled=("cancelled", "sum"),
        avg_arr_delay=("arr_delay", "mean"),
        pct_delayed=("is_delayed", "mean"),
    )
    monthly["pct_delayed"] *= 100
    return monthly


def delay_distribution(df):
    """How many flights fall in each delay category, plus summary statistics."""
    counts = df["delay_category"].value_counts(sort=False).to_frame("flights")
    counts["percent"] = counts["flights"] / len(df) * 100

    # describe() gives count, mean, min, max and the quartiles in one go.
    stats = df["arr_delay"].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.99])
    return counts, stats


def compare_airlines(df):
    """Number of flights and delay numbers per airline, busiest first."""
    airlines = df.groupby("airline", observed=True).agg(
        flights=("id", "count"),
        avg_arr_delay=("arr_delay", "mean"),
        pct_delayed=("is_delayed", "mean"),
        pct_cancelled=("cancelled", "mean"),
    )
    airlines["pct_delayed"] *= 100
    airlines["pct_cancelled"] *= 100
    return airlines.sort_values("flights", ascending=False)


def flights_per_day(df):
    """Number of flights and average arrival delay for every calendar day."""
    return df.groupby("flight_date").agg(
        flights=("id", "count"),
        avg_arr_delay=("arr_delay", "mean"),
    )


def destination_summary(df):
    """Number of flights and delay numbers for every destination, busiest first."""
    destinations = df.groupby("dest", observed=True).agg(
        flights=("id", "count"),
        avg_arr_delay=("arr_delay", "mean"),
        pct_delayed=("is_delayed", "mean"),
    )
    destinations["pct_delayed"] *= 100
    return destinations.sort_values("flights", ascending=False)


def top_destinations(df, n=10):
    """The n destinations with the most flights, and how late they arrive."""
    return destination_summary(df).head(n)


def print_findings(df):
    """Print each table and a few plain-language conclusions."""
    pd.set_option("display.width", 120)
    pd.set_option("display.float_format", "{:.1f}".format)
    arrived = df["arr_delay"].notna()

    print("=" * 60)
    print("1) FLIGHTS PER MONTH")
    print("=" * 60)
    monthly = flights_per_month(df)
    print(monthly.to_string())
    busiest, quietest = monthly["flights"].idxmax(), monthly["flights"].idxmin()
    worst = monthly["avg_arr_delay"].idxmax()
    # calendar.month_name[7] -> "July"
    print(f"\n-> Busiest month: {calendar.month_name[busiest]} ({monthly.loc[busiest, 'flights']:,} flights). "
          f"Quietest: {calendar.month_name[quietest]} ({monthly.loc[quietest, 'flights']:,}).")
    print(f"-> Worst month for delays: {calendar.month_name[worst]} "
          f"(average {monthly.loc[worst, 'avg_arr_delay']:.1f} min late, "
          f"{monthly.loc[worst, 'pct_delayed']:.1f}% of flights delayed).")

    print("\n" + "=" * 60)
    print("2) DISTRIBUTION OF ARRIVAL DELAYS (minutes)")
    print("=" * 60)
    counts, stats = delay_distribution(df)
    print(counts.to_string())
    print()
    print(stats.to_string())
    early = (df.loc[arrived, "arr_delay"] <= 0).mean() * 100
    print(f"\n-> Typical (median) flight arrives {abs(stats['50%']):.0f} min EARLY; "
          f"{early:.0f}% arrive early or exactly on time.")
    print(f"-> But the average is {stats['mean']:.1f} min LATE: a few very long delays "
          f"(up to {stats['max']:.0f} min) pull the average up. The distribution is skewed.")

    print("\n" + "=" * 60)
    print("3) AIRLINE COMPARISON (busiest first)")
    print("=" * 60)
    airlines = compare_airlines(df)
    print(airlines.to_string())
    # Ignore tiny airlines so one unlucky week can't make them 'best' or 'worst'.
    big = airlines[airlines["flights"] >= 1000]
    print(f"\n-> Most flights: {airlines.index[0]} ({airlines['flights'].iloc[0]:,}).")
    print(f"-> Lowest average delay (airlines with 1,000+ flights): "
          f"{big['avg_arr_delay'].idxmin()} ({big['avg_arr_delay'].min():.1f} min).")
    print(f"-> Highest average delay: {big['avg_arr_delay'].idxmax()} "
          f"({big['avg_arr_delay'].max():.1f} min).")

    print("\n" + "=" * 60)
    print("4) TOP 10 DESTINATIONS")
    print("=" * 60)
    top = top_destinations(df)
    print(top.to_string())
    print(f"\n-> Most popular destination: {top.index[0]} ({top['flights'].iloc[0]:,} flights).")


if __name__ == "__main__":
    print_findings(load_clean_data())
