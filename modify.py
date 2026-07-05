"""
Aggiorna fx_rates con i dati da Banca d'Italia
FIX: evita cambi invertiti (EUR/USD → 0.87)
"""

import requests
from datetime import date, timedelta
from database import get_connection

BASE_URL = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyTimeSeries"


# ------------------------
# FETCH DATI BdI
# ------------------------
def fetch_daily(base: str, quote: str, start: str, end: str) -> list:

    params = {
        "startDate": start,
        "endDate": end,
        "baseCurrencyIsoCode": quote,
        "currencyIsoCode": base,
        "lang": "it"
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=30)

        if r.status_code == 200:
            return r.json().get("rates", [])

        print(f"⚠️ Errore API BdI: {r.status_code}")
        return []

    except Exception as e:
        print(f"⚠️ Errore fetch: {e}")
        return []


# ------------------------
# MAIN UPDATE
# ------------------------
def aggiorna_cambi():
    try:
        _aggiorna_cambi_inner()
    except Exception as e:
        import traceback
        print(f"❌ ERRORE CRITICO: {e}")
        print(traceback.format_exc())


def _aggiorna_cambi_inner():

    print(f"🔄 Avvio aggiornamento cambi - {date.today()}")

    conn = get_connection()
    cur = conn.cursor()

    # tutte le coppie
    cur.execute("SELECT id, symbol FROM currency_pairs")
    coppie = cur.fetchall()

    print(f"➡️ Coppie: {len(coppie)}")

    for pair_id, symbol in coppie:

        symbol = symbol.upper().replace("-", "/")

        try:
            base, quote = symbol.split("/")
        except:
            continue

        # ultima data presente
        cur.execute(
            "SELECT MAX(date) FROM fx_rates WHERE pair_id = %s",
            (pair_id,)
        )
        last_date = cur.fetchone()[0]

        # range aggiornamento
        start = last_date + timedelta(days=1) if last_date else (date.today() - timedelta(days=30))
        end = date.today()

        if start > end:
            continue

        print(f"➡️ {symbol} | {start} → {end}")

        # fetch dati
        rates = fetch_daily(base, quote, start.isoformat(), end.isoformat())

        for item in rates:
            try:
                raw_rate = float(item["value"])
                data = item["referenceDate"]

                # ✅ FIX MINIMO (QUESTA È LA PARTE IMPORTANTE)
                if base == "EUR":
                    rate = raw_rate
                elif quote == "EUR":
                    rate = 1 / raw_rate
                else:
                    rate = raw_rate  # lasciato così per ora

                # salva rate corretto
                cur.execute("""
                    INSERT INTO fx_rates (pair_id, date, close)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (pair_id, date)
                    DO UPDATE SET close = EXCLUDED.close
                """, (pair_id, data, rate))

            except Exception as e:
                print("⚠️ errore riga:", e)

    conn.commit()
    cur.close()
    conn.close()

    print("✅ Aggiornamento completato")