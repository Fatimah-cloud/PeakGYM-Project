"""
scheduler.py
Person 2 — Backend Logic, Rules & LLM Integration

Wires together the hourly/daily/weekly/monthly jobs the whole backend
depends on, using APScheduler's BackgroundScheduler (runs in a
background thread inside the same process as the FastAPI app — no
separate worker needed for a project this size).

Jobs:
    - hourly:  stats_aggregator.run_hourly_aggregation()
               rule_engine.run_all_rules()
               llm_recommender.generate_recommendation()  (only emails/
               records something if new rules actually triggered)
    - monthly: report_generator.generate_monthly_report()  (1st of month)
               + emails it via email_sender

Wired into main.py like:
    from scheduler import start_scheduler, stop_scheduler

    @app.on_event("startup")
    def _startup():
        start_scheduler()

    @app.on_event("shutdown")
    def _shutdown():
        stop_scheduler()
"""

import logging

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
    scheduler = BackgroundScheduler()
except ImportError:
    HAS_APSCHEDULER = False
    scheduler = None

from services import stats_aggregator, rule_engine, llm_recommender, report_generator, email_sender

logging.basicConfig(level=logging.INFO, format="%(asctime)s [scheduler] %(message)s")
logger = logging.getLogger("scheduler")


def _safe_run(job_name: str, func, *args, **kwargs):
    """Run a job function without letting one failing job (e.g. missing
    API key, network hiccup) take down the scheduler or other jobs."""
    try:
        result = func(*args, **kwargs)
        logger.info(f"{job_name} completed: {result}")
        return result
    except Exception as e:
        logger.error(f"{job_name} failed: {e}")
        return None


# ---------------------------------------------------------------------
# Hourly pipeline: aggregate -> evaluate rules -> recommend -> alert
# ---------------------------------------------------------------------
def hourly_job():
    logger.info("Running hourly pipeline...")

    _safe_run("stats_aggregator", stats_aggregator.run_hourly_aggregation)
    rule_result = _safe_run("rule_engine", rule_engine.run_all_rules)

    triggered = any(
        v for k, v in (rule_result or {}).items() if k != "_raw" and isinstance(v, int) and v > 0
    )
    if not triggered:
        logger.info("No new rule triggers this hour — skipping recommendation/email.")
        return

    rec_result = _safe_run("llm_recommender", llm_recommender.generate_recommendation)
    if rec_result and rec_result.get("status") == "ok":
        _safe_run(
            "email_sender (recommendation)",
            email_sender.send_recommendation_email,
            rec_result["recommendation"],
            rec_result.get("priority", "medium"),
        )


# ---------------------------------------------------------------------
# Monthly pipeline: summarize last month -> narrative + chart -> email
# ---------------------------------------------------------------------
def monthly_job():
    logger.info("Running monthly report pipeline...")

    report = _safe_run("report_generator", report_generator.generate_monthly_report)
    if report and report.get("status") == "ok":
        _safe_run(
            "email_sender (monthly report)",
            email_sender.send_monthly_report_email,
            report["narrative"],
            report.get("chart_path"),
            report["year"],
            report["month"],
        )


# ---------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------
def start_scheduler():
    if not HAS_APSCHEDULER or scheduler is None:
        logger.warning("APScheduler is not installed; background timer jobs disabled.")
        return

    if scheduler.running:
        return

    # Hourly, on the hour
    scheduler.add_job(
        hourly_job, CronTrigger(minute=0), id="hourly_pipeline", replace_existing=True,
    )

    # Monthly, 1st of the month at 06:00 (summarizes the month that just ended)
    scheduler.add_job(
        monthly_job, CronTrigger(day=1, hour=6, minute=0),
        id="monthly_report", replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: hourly_pipeline (every hour), monthly_report (1st @ 06:00)")


def stop_scheduler():
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    # Manual test: run both pipelines once immediately, no waiting on cron.
    # Note: this calls the job functions directly and does NOT call
    # start_scheduler() — that spins up a persistent background thread
    # (correct for running inside `uvicorn main:app`, but would keep this
    # standalone script alive forever).
    print("Running hourly_job() once for testing...")
    hourly_job()
    print()
    print("Running monthly_job() once for testing...")
    monthly_job()
    print()
    print("Done — this script does not start the persistent scheduler; "
          "that happens automatically when main.py's FastAPI app starts up.")
