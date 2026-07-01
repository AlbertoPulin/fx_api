from fastapi import FastAPI, HTTPException, Query
from apscheduler.schedulers.background import BackgroundScheduler
from database import get_connection
from updater import aggiorna_cambi
from datetime import date
from typing import Optional
import threading
 
app = FastAPI(title="FX Rates API", version="1.0")
 
# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(aggiorna_cambi, 'cron', hour=7,  minute=0)
scheduler.add_job(aggiorna_cambi, 'cron', hour=18, minute=0)
scheduler.start()
 
# --- Endpoints ---
 
@app.get("/")
def root():
    return {"status": "ok", "description": "FX Rates API - Banca d'Italia"}
 
@app.get("/update")
def update():
    """Forza aggiornamento manuale dei cambi da BdI (esegue in background, non blocca la risposta HTTP)"""
    try:
        thread = threading.Thread(target=aggiorna_cambi, daemon=True)
        thread.start()
        return {"status": "ok", "message": "Aggiornamento avviato in background. Controlla i log di Render o attendi l'email di conferma."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 
@app.get("/rates/{symbol}")
def get_rates(
    symbol: str,
    date_on:  Optional[str] = Query(None, alias="date"),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date:   Optional[str] = Query(None, alias="to")
):
    """
    Ritorna il tasso di cambio per una coppia.
    Esempi:
      /rates/EUR-USD
      /rates/EUR-USD?date=2024-01-15
      /rates/EUR-USD?from=2024-01-01&to=2024-12-31
    """
    symbol_db = symbol.upper().replace("-", "/")
 
    conn = get_connection()
    cur  = conn.cursor()
 
    # Cerca coppia diretta nel DB
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (symbol_db,))
    row = cur.fetchone()
 
    if row:
        pair_id = row[0]
        return _query_rates(cur, conn, pair_id, symbol_db, date_on, from_date, to_date)
 
    # Controlla se esiste la coppia inversa (es. richiesto GBP/EUR, esiste EUR/GBP)
    base, quote = symbol_db.split("/") if "/" in symbol_db else (None, None)
    if base and quote:
        inverse_symbol = f"{quote}/{base}"
        cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (inverse_symbol,))
        inv_row = cur.fetchone()
        if inv_row:
            pair_id = inv_row[0]
            result = _query_rates_inverse(cur, conn, pair_id, symbol_db, date_on, from_date, to_date)
            return result
 
    # Nessuna coppia diretta né inversa: inferenza cross rate
    parts = symbol_db.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Formato simbolo non valido. Usa EUR-USD")
    base, quote = parts
 
    result = _cross_rate(cur, conn, base, quote, date_on, from_date, to_date)
    cur.close()
    conn.close()
    return result
 
def _query_rates(cur, conn, pair_id, symbol, date_on, from_date, to_date):
    """Query diretta su fx_rates"""
    if date_on:
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s AND date = %s
        """, (pair_id, date_on))
        rows = cur.fetchall()
    elif from_date and to_date:
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s AND date BETWEEN %s AND %s
            ORDER BY date
        """, (pair_id, from_date, to_date))
        rows = cur.fetchall()
    else:
        # Ultimo disponibile
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s
            ORDER BY date DESC LIMIT 1
        """, (pair_id,))
        rows = cur.fetchall()
 
    cur.close()
    conn.close()
 
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato trovato per {symbol}")
 
    data = [{"date": str(r[0]), "close": float(r[1])} for r in rows]
    return {"symbol": symbol, "data": data}
 
def _query_rates_inverse(cur, conn, pair_id, symbol, date_on, from_date, to_date):
    """Query su fx_rates calcolando il reciproco (1/close) per coppie inverse, es. GBP/EUR da EUR/GBP"""
    if date_on:
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s AND date = %s
        """, (pair_id, date_on))
        rows = cur.fetchall()
    elif from_date and to_date:
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s AND date BETWEEN %s AND %s
            ORDER BY date
        """, (pair_id, from_date, to_date))
        rows = cur.fetchall()
    else:
        cur.execute("""
            SELECT date, close FROM fx_rates
            WHERE pair_id = %s
            ORDER BY date DESC LIMIT 1
        """, (pair_id,))
        rows = cur.fetchall()
 
    cur.close()
    conn.close()
 
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato trovato per {symbol}")
 
    data = [{"date": str(r[0]), "close": round(1 / float(r[1]), 6)} for r in rows]
    return {"symbol": symbol, "data": data, "inferred": True}
 
def _cross_rate(cur, conn, base, quote, date_on, from_date, to_date):
    """
    Calcola cross rate al volo:
    BASE/QUOTE = (EUR/QUOTE) / (EUR/BASE)
    """
    symbol = f"{base}/{quote}"
 
    # Trova EUR/QUOTE e EUR/BASE
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (f"EUR/{quote}",))
    r1 = cur.fetchone()
    cur.execute("SELECT id FROM currency_pairs WHERE symbol = %s", (f"EUR/{base}",))
    r2 = cur.fetchone()
 
    if not r1 or not r2:
        raise HTTPException(status_code=404, detail=f"Impossibile inferire {symbol}: dati EUR/{quote} o EUR/{base} mancanti")
 
    eur_quote_id = r1[0]
    eur_base_id  = r2[0]
 
    if date_on:
        cur.execute("""
            SELECT a.date, a.close / b.close
            FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s AND a.date = %s
        """, (eur_base_id, eur_quote_id, date_on))
    elif from_date and to_date:
        cur.execute("""
            SELECT a.date, a.close / b.close
            FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s AND a.date BETWEEN %s AND %s
            ORDER BY a.date
        """, (eur_base_id, eur_quote_id, from_date, to_date))
    else:
        cur.execute("""
            SELECT a.date, a.close / b.close
            FROM fx_rates a
            JOIN fx_rates b ON b.pair_id = %s AND b.date = a.date
            WHERE a.pair_id = %s
            ORDER BY a.date DESC LIMIT 1
        """, (eur_base_id, eur_quote_id))
 
    rows = cur.fetchall()
    cur.close()
    conn.close()
 
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato per {symbol}")
 
    data = [{"date": str(r[0]), "close": round(float(r[1]), 6)} for r in rows]
    return {"symbol": symbol, "data": data, "inferred": True}
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato per {symbol}")

    data = [{"date": str(r[0]), "close": round(float(r[1]), 6)} for r in rows]
    return {"symbol": symbol, "data": data, "inferred": True}
