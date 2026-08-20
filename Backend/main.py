"""
main.py — FastAPI app entry point
Person 2 — Backend Logic, Rules & LLM Integration

Run locally with:
    uvicorn main:app --reload --port 8000

Then check:
    http://127.0.0.1:8000/            -> health check
    http://127.0.0.1:8000/docs        -> interactive API docs (Swagger)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from scheduler import start_scheduler, stop_scheduler
from live_cv_ingest import start_live_ingest, stop_live_ingest
from routers import stats, equipment, recommendations, live

app = FastAPI(
    title="Smart Gym Monitoring System API",
    description="Backend for the Smart Gym Monitoring System (Person 2 scope: "
                 "aggregation, rules, LLM recommendations, reports, email).",
    version="0.1.0",
)

# Allow the frontend (served separately, e.g. Live Server on another port)
# to call this API during development. Tighten this before deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler()
    start_live_ingest()   # runs the real CV pipeline continuously in the
                           # background, writing real detections into
                           # stats_store.db (loops demo_video.mp4)


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()
    stop_live_ingest()


@app.get("/")
def health_check():
    return {"status": "ok", "service": "smart-gym-backend"}


# --- Registered routers ---
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(equipment.router, prefix="/equipment", tags=["equipment"])
app.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
app.include_router(live.router, prefix="/live", tags=["live"])
