"""
build_report.py
Person 2 — Backend Logic, Rules & LLM Integration

Builds a single polished .docx report combining the latest monthly
report's narrative text + its chart image. Run this AFTER generating
the monthly report (via the API or generate_monthly_report()).

Usage (from backend/ folder, with the venv active):
    python data/reports/build_report.py

Output: data/reports/monthly_report_<year>-<month>.docx
"""

import sys
import json
import subprocess
from pathlib import Path
from calendar import month_name

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from database import get_connection  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parent
BUILD_SCRIPT = REPORTS_DIR / "build_report_docx.js"


def main():
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM llm_recommendations
           WHERE report_type = 'monthly'
           ORDER BY timestamp DESC LIMIT 1"""
    ).fetchone()
    conn.close()

    if not row:
        print("No monthly report found yet. Generate one first "
              "(POST /recommendations/monthly-report/generate).")
        return

    period = json.loads(row["based_on_triggers"] or "{}")
    year = period.get("year")
    month = period.get("month")
    m_name = month_name[month] if month else "Unknown"

    chart_path = REPORTS_DIR / f"monthly_{year}-{month:02d}.png"
    out_path = REPORTS_DIR / f"monthly_report_{year}-{month:02d}.docx"

    subprocess.run(
        [
            "node", str(BUILD_SCRIPT),
            row["recommendation_text"],
            str(year), m_name,
            str(chart_path), str(out_path),
        ],
        check=True,
    )
    print(f"\nDone! Open it at: {out_path}")


if __name__ == "__main__":
    main()
