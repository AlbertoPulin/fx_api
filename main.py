from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from apscheduler.schedulers.background import BackgroundScheduler
from updater import aggiorna_cambi
from routes.v1.fx import router as fx_router_v1, limiter

app = FastAPI(title="FX Rates API", version="1.0")

# Rate limiting globale: se un IP sfora, risponde 429 invece di far arrivare la richiesta al DB
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(fx_router_v1, prefix="/api/v1")

# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(aggiorna_cambi, 'cron', hour=7,  minute=0)
scheduler.add_job(aggiorna_cambi, 'cron', hour=18, minute=0)
scheduler.start()

@app.get("/")
def root():
    return {"status": "ok", "description": "FX Rates API - Banca d'Italia"}
