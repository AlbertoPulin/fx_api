from fastapi import FastAPI, HTTPException, Query, Response
from apscheduler.schedulers.background import BackgroundScheduler
from database import get_connection
from updater import aggiorna_cambi
from datetime import date
from typing import Optional
import threading
import xml.etree.ElementTree as ET

app = FastAPI(title="FX Rates API", version="1.0")

# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(aggiorna_cambi, 'cron', hour=7,  minute=0)
scheduler.add_job(aggiorna_cambi, 'cron', hour=18, minute=0)
scheduler.start()

# --- Helpers ---

def to_xml(symbol: str, data: list) -> str:
    root = ET.Element("FxRates")
    ET.SubElement(root, "Symbol").text = symbol
    rates = ET.SubElement(root, "Rates")
    for r in data:
        rate = ET.SubElement(rates, "Rate")
        ET.SubElement(rate, "Date").text  = r["date"]
        ET.SubElement(rate, "Close").text = str(r["close"])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")

def build_response(symbol: str, data: list, fmt: str):
    if fmt == "xml":
        return Response(content=to_xml(symbol, data), media_type="application/xml")
    return {"symbol": symbol, "data": data}

# --- Endpoints ---

@app.get("/")
def root():
    return {"status": "ok", "description": "FX Rates API - Banca d'Italia"}

@app.get("/update")
def update():
    """Forza aggiornamento manuale dei cambi da BdI"""
    try:
        thread = threading.Thread(target=aggiorna_cambi, daemon=True)
        thread.start()
        return {"status": "ok", "message": "Aggiornamento avviato in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rates/{symbol}")
def get_rates(
    symbol:    str,
    date_on:   Optional[str] = Query(None, alias="date"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date:   Optional[str] = Query(None, alias="to"),
    fmt:       Optional[str] = Query("json", alias="format")
):
    """
    Ritorna il tasso di cambio per una coppia.
    Esempi:
      /rates/EUR-USD
      /rates/EUR-USD?date=2024-01-15
      /rates/EUR-USD?from=2024-01-01&to=2024-12-31
      /rates/EUR-USD?date=2024-01-15&format=xml
    """
    symbol_db = symbol.upper().replace("-", "/")

    conn = get_connection()
    cur  = conn.cursor()

    # 1. Coppia diretta
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (symbol_db,))
    row = cur.fetchone()
    if row:
        return _query_rates(cur, conn, row[0], symbol_db, date_on, from_date, to_date, fmt)

    # 2. Coppia inversa
    parts = symbol_db.split("/")
    if len(parts) == 2:
        base, quote = parts
        cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (f"{quote}/{base}",))
        inv = cur.fetchone()
        if inv:
            return _query_rates_inverse(cur, conn, inv[0], symbol_db, date_on, from_date, to_date, fmt)

        # 3. Cross rate
        return _cross_rate(cur, conn, base, quote, date_on, from_date, to_date, fmt)

    raise HTTPException(status_code=400, detail="Formato simbolo non valido. Usa EUR-USD")

def _query_rates(cur, conn, pair_id, symbol, date_on, from_date, to_date, fmt):
    if date_on:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s AND date = %s", (pair_id, date_on))
    elif from_date and to_date:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s AND date BETWEEN %s AND %s ORDER BY date", (pair_id, from_date, to_date))
    else:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s ORDER BY date DESC LIMIT 1", (pair_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato per {symbol}")
    data = [{"date": str(r[0]), "close": float(r[1])} for r in rows]
    return build_response(symbol, data, fmt)

def _query_rates_inverse(cur, conn, pair_id, symbol, date_on, from_date, to_date, fmt):
    if date_on:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s AND date = %s", (pair_id, date_on))
    elif from_date and to_date:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s AND date BETWEEN %s AND %s ORDER BY date", (pair_id, from_date, to_date))
    else:
        cur.execute("SELECT date, close FROM fx_rates WHERE pair_id = %s ORDER BY date DESC LIMIT 1", (pair_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato per {symbol}")
    data = [{"date": str(r[0]), "close": round(1 / float(r[1]), 6)} for r in rows]
    return build_response(symbol, data, fmt)

def _cross_rate(cur, conn, base, quote, date_on, from_date, to_date, fmt):
    symbol = f"{base}/{quote}"
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (f"EUR/{quote}",))
    r1 = cur.fetchone()
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (f"EUR/{base}",))
    r2 = cur.fetchone()
    if not r1 or not r2:
        raise HTTPException(status_code=404, detail=f"Impossibile inferire {symbol}")
    eur_quote_id = r1[0]
    eur_base_id  = r2[0]
    if date_on:
        cur.execute("""
            SELECT a.date, a.close / b.close FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s AND a.date = %s
        """, (eur_base_id, eur_quote_id, date_on))
    elif from_date and to_date:
        cur.execute("""
            SELECT a.date, a.close / b.close FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s AND a.date BETWEEN %s AND %s ORDER BY a.date
        """, (eur_base_id, eur_quote_id, from_date, to_date))
    else:
        cur.execute("""
            SELECT a.date, a.close / b.close FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s ORDER BY a.date DESC LIMIT 1
        """, (eur_base_id, eur_quote_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato per {symbol}")
    data = [{"date": str(r[0]), "close": round(float(r[1]), 6)} for r in rows]
    return build_response(symbol, data, fmt)
