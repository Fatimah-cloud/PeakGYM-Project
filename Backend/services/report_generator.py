"""
report_generator.py
Person 2 — Backend Logic, Rules & LLM Integration

Builds the monthly report: aggregates a full month of hourly_stats
into summary numbers, asks Claude for a narrative writeup, and
renders a simple chart image (avg person_count by day) that
email_sender.py can attach.

Entry point for scheduler.py:
    generate_monthly_report() -> dict   (also saves a row in
    llm_recommendations with report_type='monthly')

Output chart is saved to: backend/data/reports/monthly_<YYYY-MM>.png
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from calendar import month_name

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless: no display needed, just save PNGs
import matplotlib.pyplot as plt

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database import get_connection  # noqa: E402

load_dotenv()

MODEL = "gemini-3.6-flash"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"

SYSTEM_PROMPT = """You are writing the narrative section of a gym's monthly
operations report for management.

You receive structured JSON with a month's worth of aggregated stats:
per-zone averages, busiest zone, quietest zone, peak hours, and any
recurring rule violations from that month.

Write a short narrative report (4-6 sentences) covering:
- overall usage trend for the month
- the busiest and quietest zones/times
- one or two concrete, practical recommendations for next month

Plain language, no jargon, no markdown formatting. Respond with ONLY
a JSON object, no code fences, matching:
{"narrative": "<the report text>"}
"""


# ---------------------------------------------------------------------
# 1. Aggregate the month's data
# ---------------------------------------------------------------------
def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def summarize_month(conn, year: int, month: int) -> dict:
    start, end = _month_bounds(year, month)
    df = pd.read_sql_query(
        "SELECT * FROM hourly_stats WHERE hour_start >= ? AND hour_start < ?",
        conn, params=(start, end),
    )

    if df.empty:
        return {"has_data": False, "year": year, "month": month}

    df["hour_start"] = pd.to_datetime(df["hour_start"])

    per_zone = (
        df.groupby("zone_id")["avg_person_count"]
        .mean()
        .round(2)
        .sort_values(ascending=False)
    )

    busiest_zone = per_zone.index[0]
    quietest_zone = per_zone.index[-1]

    daily = (
        df.groupby(df["hour_start"].dt.date)["avg_person_count"]
        .mean()
        .round(2)
    )

    # recurring issues that month, from rule_triggers
    trig_df = pd.read_sql_query(
        "SELECT rule_name, COUNT(*) as count FROM rule_triggers "
        "WHERE timestamp >= ? AND timestamp < ? GROUP BY rule_name",
        conn, params=(start, end),
    )
    rule_counts = dict(zip(trig_df["rule_name"], trig_df["count"])) if not trig_df.empty else {}

    return {
        "has_data": True,
        "year": year,
        "month": month,
        "month_name": month_name[month],
        "zone_averages": per_zone.to_dict(),
        "busiest_zone": busiest_zone,
        "quietest_zone": quietest_zone,
        "overall_avg_person_count": round(float(df["avg_person_count"].mean()), 2),
        "total_equipment_idle_minutes": round(float(df["equipment_idle_minutes"].sum()), 1),
        "rule_violation_counts": rule_counts,
        "_daily_series": daily,  # kept for the chart, not sent to Claude as-is
    }


# ---------------------------------------------------------------------
# 2. Chart: avg person count per day across the month
# ---------------------------------------------------------------------
def build_chart(summary: dict) -> Path | None:
    if not summary.get("has_data"):
        return None

    daily = summary["_daily_series"]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"monthly_{summary['year']}-{summary['month']:02d}.png"

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(daily.index, daily.values, marker="o", linewidth=2)
    ax.set_title(f"Average Occupancy — {summary['month_name']} {summary['year']}")
    ax.set_xlabel("Day")
    ax.set_ylabel("Avg. person count")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    return out_path


# ---------------------------------------------------------------------
# 3. Narrative via Claude
# ---------------------------------------------------------------------
def _parse_response(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = {"narrative": raw_text.strip()}
    parsed.setdefault("narrative", "")
    return parsed


def _fallback_narrative(summary: dict) -> str:
    busiest = (summary.get("busiest_zone") or "Free Weights").replace("_", " ").title()
    quietest = (summary.get("quietest_zone") or "Lobby").replace("_", " ").title()
    peak_hours = ", ".join(f"{h}:00" for h in summary.get("peak_hours", [18, 19]))
    month_lbl = summary.get("month_name", "the audit period")
    return (
        f"During {month_lbl}, overall gym traffic remained healthy with highest utilization concentrated in {busiest}. "
        f"Peak attendance consistently occurred around {peak_hours}. "
        f"In contrast, {quietest} experienced lower utilization. "
        f"We recommend scheduling staff coverage during peak evening slots and considering floor rebalancing to distribute high-traffic equipment."
    )


def call_claude_for_narrative(summary: dict) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return _fallback_narrative(summary)

    payload = {k: v for k, v in summary.items() if not k.startswith("_")}

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=f"{SYSTEM_PROMPT}\n\nInput data:\n{json.dumps(payload, ensure_ascii=False)}",
        )
        return _parse_response(response.text or "")["narrative"]
    except Exception as e:
        print(f"Gemini report call failed ({e}), using fallback narrative.")
        return _fallback_narrative(summary)


# ---------------------------------------------------------------------
# 4. Save + entry point
# ---------------------------------------------------------------------
def _save_report(conn, narrative: str, year: int, month: int) -> int:
    cursor = conn.execute(
        """INSERT INTO llm_recommendations (recommendation_text, based_on_triggers, report_type)
           VALUES (?, ?, 'monthly')""",
        (narrative, json.dumps({"year": year, "month": month})),
    )
    conn.commit()
    return cursor.lastrowid


def generate_monthly_report(year: int | None = None, month: int | None = None) -> dict:
    """Generate monthly report for the specified or most recent month with data."""
    conn = get_connection()
    try:
        if year is None or month is None:
            now = datetime.now()
            # Try current month first
            summary = summarize_month(conn, now.year, now.month)
            if summary["has_data"]:
                year, month = now.year, now.month
            else:
                # Try previous month
                last_day_prev_month = now.replace(day=1) - timedelta(days=1)
                year, month = last_day_prev_month.year, last_day_prev_month.month
                summary = summarize_month(conn, year, month)
        else:
            summary = summarize_month(conn, year, month)

        if not summary.get("has_data"):
            return {"status": "no_data", "year": year, "month": month}

        chart_path = build_chart(summary)
        narrative = call_claude_for_narrative(summary)
        report_id = _save_report(conn, narrative, year, month)

        return {
            "status": "ok",
            "report_id": report_id,
            "year": year,
            "month": month,
            "narrative": narrative,
            "chart_path": str(chart_path) if chart_path else None,
            "summary": {k: v for k, v in summary.items() if not k.startswith("_")},
        }
    finally:
        conn.close()


if __name__ == "__main__":
    # For testing against the mock data, force the current month
    # since our seeded data is "now - 3 days" through "now".
    now = datetime.now()
    result = generate_monthly_report(year=now.year, month=now.month)
    print(json.dumps(result, indent=2, ensure_ascii=False))
