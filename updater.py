"""
Aggiorna fx_rates con i dati mancanti da Banca d'Italia.
- Scarica solo EUR e USD come base
- Parte dall'ultima data PER COPPIA fino a oggi
- Invia email di notifica via Resend
"""

import requests
import time
from datetime import date, timedelta
from database import get_connection

BASE_URL    = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyTimeSeries"
RESEND_KEY  = "re_Kr5LULLT_ELxsXU3fRATb7jcAQVaBLGYg"
EMAIL_FROM  = "onboarding@resend.dev"
EMAIL_TO    = "albertopulin5@gmail.com"

def invia_email(oggetto: str, corpo: str):
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from":    EMAIL_FROM,
                "to":      [EMAIL_TO],
                "subject": oggetto,
                "text":    corpo
            }
        )
        if r.status_code in (200, 201):
            print("📧 Email inviata")
        else:
            print(f"⚠️  Errore invio email: {r.status_code} {r.text}")
    except Exception as e:
        print(f"⚠️  Errore invio email: {e}")

def fetch_daily(base: str, quote: str, start: str, end: str) -> list:
    params = {
        "startDate":           start,
        "endDate":             end,
        "baseCurrencyIsoCode": base,
        "currencyIsoCode":     quote,
        "lang": "it"
    }
    headers = {"Accept": "application/json"}
    try:
        r = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json().get("rates", [])
        return []
    except Exception as e:
        print(f"⚠️  Errore {base}/{quote}: {e}")
        return []

def aggiorna_cambi():
    try:
        _aggiorna_cambi_inner()
    except Exception as e:
        import traceback
        print(f"❌ ERRORE CRITICO in aggiorna_cambi: {e}")
        print(traceback.format_exc())

def _aggiorna_cambi_inner():
    print(f"🔄 Avvio aggiornamento cambi - {date.today()}")

    conn = get_connection()
    cur  = conn.cursor()

    end_date = date.today()

    # Carica solo coppie EUR e USD
    cur.execute("""
        SELECT id, base, quote FROM currency_pairs
        WHERE base IN ('EUR', 'USD')
        ORDER BY symbol
    """)
    coppie = cur.fetchall()
    print(f"📋 {len(coppie)} coppie da aggiornare")

    totale = 0
    errori = 0
    for i, (pair_id, base, quote) in enumerate(coppie, 1):

        # Ultima data PER QUESTA COPPIA
        cur.execute("SELECT MAX(date) FROM fx_rates WHERE pair_id = %s", (pair_id,))
        last_date = cur.fetchone()[0]

        if last_date is None:
            start_date = date(2001, 1, 1)
        else:
            start_date = last_date + timedelta(days=1)

        if start_date > end_date:
            continue  # già aggiornata, salta

        if i % 50 == 0 or i == 1:
            print(f"   ⏳ [{i}/{len(coppie)}] {base}/{quote} dal {start_date}...")

        rates = fetch_daily(base, quote, str(start_date), str(end_date))
        if not rates:
            time.sleep(0.1)
            continue

        inseriti = 0
        for r in rates:
            ref_date = r.get("referenceDate")
            avg_rate = r.get("avgRate") or r.get("avrgRate")
            if not ref_date or avg_rate is None:
                continue
            try:
                cur.execute("""
                    INSERT INTO fx_rates (pair_id, date, close)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (pair_id, date) DO NOTHING
                """, (pair_id, ref_date, avg_rate))
                if cur.rowcount == 1:
                    inseriti += 1
            except Exception as e:
                conn.rollback()
                print(f"❌ {base}/{quote} {ref_date}: {e}")
                errori += 1
                continue

        conn.commit()
        totale += inseriti
        time.sleep(0.2)

    cur.close()
    conn.close()

    print(f"✅ Aggiornamento completato: {totale} nuove righe inserite")

    invia_email(
        f"FX API - Aggiornamento completato {date.today()}",
        f"""Aggiornamento cambi completato.

Righe inserite: {totale}
Errori:         {errori}
Coppie:         {len(coppie)} (EUR e USD)

FX API - Banca d'Italia
"""
    )
