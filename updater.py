
"""
Aggiorna fx_rates con i dati mancanti da Banca d'Italia.
- Scarica solo EUR e USD come base
- Parte dall'ultima data presente nel DB fino a oggi
- Invia email di notifica al completamento
"""

import requests
import time
import smtplib
from email.mime.text import MIMEText
from datetime import date, timedelta
from database import get_connection

BASE_URL = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyTimeSeries"

# Configurazione email
EMAIL_FROM     = "albertopulin5@gmail.com"
EMAIL_TO       = "albertopulin5@gmail.com"
EMAIL_PASSWORD = "tnjq wkwg upyy yjtn"  # App Password Gmail (non la password normale)
SMTP_SERVER    = "smtp.gmail.com"
SMTP_PORT      = 587

def invia_email(oggetto: str, corpo: str):
    try:
        msg = MIMEText(corpo)
        msg["Subject"] = oggetto
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print("📧 Email inviata")
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
    print(f"🔄 Avvio aggiornamento cambi - {date.today()}")

    conn = get_connection()
    cur  = conn.cursor()

    # Ultima data presente nel DB
    cur.execute("SELECT MAX(date) FROM fx_rates")
    last_date = cur.fetchone()[0]

    if last_date is None:
        start_date = date(2001, 1, 1)
    else:
        start_date = last_date + timedelta(days=1)

    end_date = date.today()

    if start_date > end_date:
        print("✅ DB già aggiornato")
        cur.close()
        conn.close()
        invia_email(
            "FX API - Nessun aggiornamento necessario",
            f"Il DB è già aggiornato all'ultima data disponibile ({last_date})."
        )
        return

    print(f"📅 Scarico {start_date} → {end_date}")

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
    for pair_id, base, quote in coppie:
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

Data scaricata: {start_date} → {end_date}
Righe inserite: {totale}
Errori:         {errori}
Coppie:         {len(coppie)} (EUR e USD)

FX API - Banca d'Italia
"""
    )