"""
Stage 5 - Interactive flight dashboard built with Dash.

Run it from the project folder (after data_prep.py):
    python src/app.py
then open http://127.0.0.1:8050 in your browser.

How it works, in short:
  1. The cleaned Parquet file is loaded ONCE when the app starts.
  2. The layout describes what is on the page (filters, cards, charts).
  3. One callback runs every time a filter changes: it filters the table with
     pandas, summarises it, and sends back new numbers and charts.
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html
from plotly.subplots import make_subplots

from analysis import compare_airlines, destination_summary, flights_per_day, load_clean_data

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

ON_TIME_LIMIT = 15  # minutes; same rule as data_prep.py

# Histogram range. Almost all flights fall between -90 and 300 minutes;
# the few longer delays would squash the chart, so we count them separately.
HIST_MIN, HIST_MAX, HIST_STEP = -90, 300, 5

# Colours for the dark theme. Chart colours were checked for colour-blind
# safety and contrast against the card background.
SURFACE = "#1a1a19"      # card / chart background
TEXT = "#f0efec"         # main text
TEXT_MUTED = "#898781"   # axis labels
GRID = "#2c2c2a"         # thin grid lines
BASELINE = "#383835"     # the zero line
BLUE = "#3987e5"         # main data colour
ORANGE = "#d95926"       # second measure (delay over time)
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# ---------------------------------------------------------------------------
# Load the data once, at startup (never inside a callback - that would be slow)
# ---------------------------------------------------------------------------

# Only the columns the dashboard uses. Loading all 29 columns would need about
# 150 MB more memory, which matters on small free hosting plans (512 MB).
APP_COLUMNS = ["id", "flight_date", "dest", "airline", "arr_delay", "is_delayed", "cancelled"]
FLIGHTS = load_clean_data(columns=APP_COLUMNS)
FIRST_DATE = FLIGHTS["flight_date"].min()
LAST_DATE = FLIGHTS["flight_date"].max()

AIRLINE_OPTIONS = sorted(FLIGHTS["airline"].unique())
DEST_OPTIONS = sorted(FLIGHTS["dest"].unique())


# ---------------------------------------------------------------------------
# Data helpers (plain functions, so we can also test them without the app)
# ---------------------------------------------------------------------------

def filter_flights(df, start_date=None, end_date=None, destinations=None, airlines=None):
    """Return only the flights that match the chosen filters.

    An empty filter (None or an empty list) means "no limit".
    """
    keep = pd.Series(True, index=df.index)
    if start_date:
        keep &= df["flight_date"] >= pd.Timestamp(start_date).normalize()
    if end_date:
        # <= so the end date itself is included.
        keep &= df["flight_date"] <= pd.Timestamp(end_date).normalize()
    if destinations:
        keep &= df["dest"].isin(destinations)
    if airlines:
        keep &= df["airline"].isin(airlines)
    return df[keep]


def compute_kpis(df):
    """The four headline numbers for the cards.

    Average delay and % delayed only use flights that actually arrived,
    because cancelled/diverted flights have no arrival delay.
    """
    return {
        "total_flights": len(df),
        "avg_delay": df["arr_delay"].mean(),
        "pct_delayed": df["is_delayed"].mean() * 100,
        "pct_cancelled": df["cancelled"].mean() * 100,
    }


def delay_histogram_counts(df):
    """Count flights in 5-minute delay bins (done in pandas, not in the browser).

    Returns the counts per bin and how many flights fell outside the range.
    """
    bins = range(HIST_MIN, HIST_MAX + HIST_STEP, HIST_STEP)
    delays = df["arr_delay"].dropna()
    counts = pd.cut(delays, bins=bins).value_counts(sort=False)
    outside = len(delays) - counts.sum()
    return counts, outside


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def apply_dark_style(fig, height):
    """Give every chart the same dark look."""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=20, t=40, b=10),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=TEXT_MUTED, size=12),
        showlegend=False,
        hoverlabel=dict(bgcolor="#2c2c2a", bordercolor=GRID, font=dict(color=TEXT, family=FONT)),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=BASELINE, linecolor=BASELINE, automargin=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=BASELINE, linecolor=BASELINE, automargin=True)
    return fig


def empty_figure(height):
    """A blank chart with a message, shown when no flights match the filters."""
    fig = go.Figure()
    fig.add_annotation(text="No flights match these filters", showarrow=False,
                       font=dict(size=14, color=TEXT_MUTED))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_dark_style(fig, height)


def make_timeline_figure(df):
    """Chart 1: flights per day (top) and average delay per day (bottom).

    Two panels sharing the date axis, instead of two y-axes on one chart,
    because two different scales on one chart can suggest fake patterns.
    """
    daily = flights_per_day(df)
    # Add days with zero flights (possible with narrow filters) so the line
    # drops to 0 instead of jumping over the missing day.
    all_days = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(all_days)
    daily["flights"] = daily["flights"].fillna(0)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                        subplot_titles=("Flights per day", "Average arrival delay per day (minutes)"))
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["flights"], mode="lines", line=dict(color=BLUE, width=2),
        hovertemplate="%{x|%a %b %d}<br>%{y:,} flights<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["avg_arr_delay"], mode="lines", line=dict(color=ORANGE, width=2),
        hovertemplate="%{x|%a %b %d}<br>%{y:.1f} min average delay<extra></extra>",
    ), row=2, col=1)
    fig.update_annotations(font=dict(color=TEXT, size=13), x=0, xanchor="left")
    fig.update_layout(hovermode="x")
    return apply_dark_style(fig, height=420)


def make_histogram_figure(df):
    """Chart 2: how many flights had each size of arrival delay."""
    counts, outside = delay_histogram_counts(df)
    bin_starts = [interval.left for interval in counts.index]
    bin_ends = [interval.right for interval in counts.index]

    fig = go.Figure(go.Bar(
        x=[start + HIST_STEP / 2 for start in bin_starts],  # centre of each bin
        y=counts.values,
        width=HIST_STEP,
        marker=dict(color=BLUE, line=dict(color=SURFACE, width=1)),
        customdata=list(zip(bin_starts, bin_ends)),
        hovertemplate="%{customdata[0]} to %{customdata[1]} min<br>%{y:,} flights<extra></extra>",
    ))
    # Mark the 15-minute "on time" limit.
    fig.add_vline(x=ON_TIME_LIMIT, line=dict(color=TEXT_MUTED, width=1, dash="dot"),
                  annotation_text="15 min: on-time limit", annotation_position="top right",
                  annotation_font=dict(color=TEXT_MUTED))
    fig.update_layout(
        title=dict(text="Distribution of arrival delays", font=dict(color=TEXT, size=13), x=0.01),
        bargap=0,
    )
    fig.update_xaxes(title_text=f"Minutes late (negative = early) · {outside:,} flights over {HIST_MAX} min not shown")
    fig.update_yaxes(title_text="Flights")
    return apply_dark_style(fig, height=360)


def pick_scatter_labels(dest):
    """Choose the few destinations worth writing on the scatter plot.

    Labelling every dot would be unreadable, and the busiest airports sit so
    close together that their labels overlap. So we label the busiest one plus
    the most and least delayed among routes with at least ~1 flight a day.
    """
    labels = {dest["flights"].idxmax()}
    regular = dest[dest["flights"] >= 365]
    if not regular.empty:
        labels.add(regular["avg_arr_delay"].idxmax())
        labels.add(regular["avg_arr_delay"].idxmin())
    return labels


def make_scatter_figure(df):
    """Chart 3: one dot per destination - is a busy route also a late route?"""
    dest = destination_summary(df).dropna(subset=["avg_arr_delay"])
    # Only a few dots get a text label; hovering over any dot shows its details.
    chosen = pick_scatter_labels(dest)
    labels = [code if code in chosen else "" for code in dest.index]

    fig = go.Figure(go.Scatter(
        x=dest["flights"], y=dest["avg_arr_delay"],
        mode="markers+text", text=labels, textposition="top center",
        textfont=dict(color=TEXT, size=11),
        marker=dict(color=BLUE, size=9, line=dict(color=SURFACE, width=2)),
        customdata=list(zip(dest.index, dest["pct_delayed"])),
        hovertemplate=("<b>%{customdata[0]}</b><br>%{x:,} flights<br>"
                       "%{y:.1f} min average delay<br>%{customdata[1]:.1f}% delayed<extra></extra>"),
    ))
    fig.update_layout(title=dict(text="Destinations: number of flights vs. average delay",
                                 font=dict(color=TEXT, size=13), x=0.01))
    # Log scale: destinations range from 1 to 17,000+ flights. On a normal axis
    # nearly every dot would be squashed against the left edge.
    fig.update_xaxes(type="log", title_text="Number of flights (log scale)")
    fig.update_yaxes(title_text="Average arrival delay (min)")
    return apply_dark_style(fig, height=360)


def make_airline_figure(df):
    """Chart 4: average arrival delay per airline, with its number of flights."""
    airlines = compare_airlines(df).dropna(subset=["avg_arr_delay"])
    airlines = airlines.sort_values("avg_arr_delay")  # most delayed ends up on top

    fig = go.Figure(go.Bar(
        x=airlines["avg_arr_delay"], y=airlines.index, orientation="h",
        marker=dict(color=BLUE, cornerradius=4),
        text=[f"{delay:.1f} min · {n:,} flights"
              for delay, n in zip(airlines["avg_arr_delay"], airlines["flights"])],
        textposition="outside", textfont=dict(color=TEXT_MUTED),
        cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>%{x:.1f} min average delay<extra></extra>",
    ))
    fig.update_layout(title=dict(text="Airlines: average arrival delay (minutes)",
                                 font=dict(color=TEXT, size=13), x=0.01),
                      bargap=0.35)
    # Leave empty space past the bar tips so the text labels fit: on the
    # right always, and on the left only if some airline is early on average.
    lowest = min(airlines["avg_arr_delay"].min(), 0)
    highest = max(airlines["avg_arr_delay"].max(), 0)
    padding = 0.35 * (highest - lowest) + 1
    left_edge = lowest - padding if lowest < 0 else 0
    fig.update_xaxes(title_text="Average arrival delay (min)", range=[left_edge, highest + padding])
    fig.update_yaxes(tickfont=dict(color=TEXT))
    # About 28px of height per airline keeps bars thin no matter how many are shown.
    return apply_dark_style(fig, height=90 + 28 * len(airlines))


# ---------------------------------------------------------------------------
# Layout - what the page looks like
# ---------------------------------------------------------------------------

def kpi_card(card_id, title, note):
    """One headline-number card. The value is filled in by the callback."""
    return html.Div(className="card kpi", children=[
        html.Div(title, className="kpi-title"),
        html.Div(id=card_id, className="kpi-value"),
        html.Div(note, className="kpi-note"),
    ])


def chart_card(graph_id, wide=False):
    """A card that holds one chart."""
    return html.Div(className="card wide" if wide else "card", children=[
        dcc.Graph(id=graph_id, config={"displayModeBar": False}),
    ])


# assets_folder: Dash automatically loads every .css file in this folder.
app = Dash(__name__, title="Flight Delays Dashboard",
           assets_folder=str(Path(__file__).parent / "assets"))

# The web server inside Dash. Online hosting runs it with gunicorn
# (a production web server) instead of app.run(): see the Dockerfile.
server = app.server

app.layout = html.Div(className="page", children=[
    html.Header(className="header", children=[
        html.H1("NYC Flights 2013 · Delay Dashboard"),
        html.P("All 336,776 flights that left New York (JFK, LGA, EWR) in 2013. "
               "Delays are arrival delays in minutes."),
    ]),

    html.Div(className="filters card", children=[
        html.Div(className="filter", children=[
            html.Label("Date range"),
            dcc.DatePickerRange(
                id="date-range",
                min_date_allowed=FIRST_DATE.date(), max_date_allowed=LAST_DATE.date(),
                start_date=FIRST_DATE.date(), end_date=LAST_DATE.date(),
                initial_visible_month=FIRST_DATE.date(),
            ),
        ]),
        html.Div(className="filter", children=[
            html.Label("Destination"),
            dcc.Dropdown(id="dest-filter", options=DEST_OPTIONS, multi=True,
                         placeholder="All destinations"),
        ]),
        html.Div(className="filter", children=[
            html.Label("Airline"),
            dcc.Dropdown(id="airline-filter", options=AIRLINE_OPTIONS, multi=True,
                         placeholder="All airlines"),
        ]),
    ]),

    html.Div(className="kpi-grid", children=[
        kpi_card("kpi-flights", "Total flights", "scheduled, incl. cancelled"),
        kpi_card("kpi-delay", "Average arrival delay", "of flights that arrived"),
        kpi_card("kpi-delayed", "Delayed flights", f"> {ON_TIME_LIMIT} min late, of flights that arrived"),
        kpi_card("kpi-cancelled", "Cancelled flights", "of scheduled flights"),
    ]),

    html.Div(className="chart-grid", children=[
        chart_card("timeline-chart", wide=True),
        chart_card("histogram-chart"),
        chart_card("scatter-chart"),
        chart_card("airline-chart", wide=True),
    ]),
])


# ---------------------------------------------------------------------------
# Callback - runs every time a filter changes
# ---------------------------------------------------------------------------

@app.callback(
    Output("kpi-flights", "children"),
    Output("kpi-delay", "children"),
    Output("kpi-delayed", "children"),
    Output("kpi-cancelled", "children"),
    Output("timeline-chart", "figure"),
    Output("histogram-chart", "figure"),
    Output("scatter-chart", "figure"),
    Output("airline-chart", "figure"),
    Input("date-range", "start_date"),
    Input("date-range", "end_date"),
    Input("dest-filter", "value"),
    Input("airline-filter", "value"),
)
def update_dashboard(start_date, end_date, destinations, airlines):
    filtered = filter_flights(FLIGHTS, start_date, end_date, destinations, airlines)

    if filtered.empty:
        return ("–", "–", "–", "–", empty_figure(420), empty_figure(360),
                empty_figure(360), empty_figure(300))

    kpis = compute_kpis(filtered)

    # If every matching flight was cancelled there is no delay to show.
    if pd.isna(kpis["avg_delay"]):
        avg_delay_text = delayed_text = "–"
    else:
        avg_delay_text = f"{kpis['avg_delay']:.1f} min"
        delayed_text = f"{kpis['pct_delayed']:.1f}%"

    has_arrivals = filtered["arr_delay"].notna().any()
    return (
        f"{kpis['total_flights']:,}",
        avg_delay_text,
        delayed_text,
        f"{kpis['pct_cancelled']:.1f}%",
        make_timeline_figure(filtered),
        make_histogram_figure(filtered) if has_arrivals else empty_figure(360),
        make_scatter_figure(filtered) if has_arrivals else empty_figure(360),
        make_airline_figure(filtered) if has_arrivals else empty_figure(300),
    )


if __name__ == "__main__":
    # debug=True would reload the app when you save a file - handy while coding.
    app.run(host="127.0.0.1", port=8050, debug=False)
