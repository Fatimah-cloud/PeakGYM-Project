# PeakGYM - Smart Gym Monitoring System

An end-to-end facility analytics system for gyms: a computer-vision pipeline detects
people and equipment usage from camera footage, a FastAPI backend aggregates that
into stats/heatmaps and rule-based alerts, an LLM (Gemini) turns those into staff
recommendations and monthly reports, and a web dashboard visualizes everything live.

```
## Getting started

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install                     # only needed for .docx monthly report generation
```

Copy the environment template and fill in your own keys:

```bash
cp .env.example .env
```

| Variable | Required for | Notes |
|---|---|---|
| `GEMINI_API_KEY` | AI recommendations & monthly reports | Free tier at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `RESEND_API_KEY` | Email alerts | Optional — [resend.com](https://resend.com) |
| `GYM_STAFF_EMAIL` | Email alerts | Who receives alerts/reports |
| `ALERT_FROM_EMAIL` | Email alerts | Defaults to `onboarding@resend.dev` |


Run the API:

```bash
uvicorn main:app --reload --port 8000
```

- API base URL: `http://127.0.0.1:8000`
- Interactive docs: `http://127.0.0.1:8000/docs`

The database (`backend/data/stats_store.db`) is created automatically on first run.
```

### Frontend

The dashboard is a static site — open `frontend/index.html` directly, or serve it
with any static server (e.g. VS Code Live Server) so it can call the backend API
during development. CORS is open by default for local dev.

### Running the CV pipeline on your own video

```bash
cd backend
python run_pipeline.py --video test_assets/demo_video.mp4 --display
```


