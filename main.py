from fastapi import FastAPI
from database import get_connection

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/test-db")
def test_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM fx_rates")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"fx_rates_rows": count}