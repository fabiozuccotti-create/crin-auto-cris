import csv
import io
import json
import os
import re
import time
from collections import defaultdict
import requests

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
USERNAME = os.environ.get("QUOTER_USER", "").strip()
PASSWORD = os.environ.get("QUOTER_PASS", "").strip()

URL_LOGIN = "https://quoter.it/site/login"
URL_RINOLEGGIO = "https://quoter.it/v2/deal"
URL_REPORT_STOCK = "https://quoter.it/proxy/deal/list?target=report&action=stock"

FILE_MEMORIA = "vetture_nuove_salvate.json"

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


def invia_telegram(messaggio):
    if not TOKEN_TELEGRAM or not CHAT_ID:
        print("Telegram non configurato (secret mancanti).")
        return
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": messaggio,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"Errore Telegram: {r.text}")
    except Exception as e:
        print(f"Errore connessione Telegram: {e}")


def invia_messaggi_frazionati(righe, limite_caratteri=3800):
    """Invia blocchi di testo formattato rispettando il limite di Telegram."""
    buffer = ""
    for riga in righe:
        if len(buffer) + len(riga) + 2 > limite_caratteri:
            invia_telegram(buffer.strip())
            time.sleep(0.8)
            buffer = riga + "\n"
        else:
            buffer += riga + "\n"
    if buffer.strip():
        invia_telegram(buffer.strip())
        time.sleep(0.8)


def genera_blocchi_raggruppati(diff_ids, source_dict, titolo, emoji, segno):
    """Raggruppa le vetture per Marca, Modello e Allestimento."""
    if not diff_ids:
        return []

    gruppi = defaultdict(list)
    for vid in diff_ids:
        info = source_dict[vid]
        make = info.get("make") or "Altro"
        model = info.get("model") or ""
        gruppi[(make, model)].append(info)

    righe_messaggio = [
        f"{emoji} <b>{titolo} ({segno}{len(diff_ids)} vetture)</b>\n"
    ]

    for (make, model), elementi in sorted(gruppi.items(), key=lambda x: (x[0][0], x[0][1])):
        conteggi_allestimenti = defaultdict(int)
        for el in elementi:
            desc = el.get("desc") or f"{make} {model}"
            conteggi_allestimenti[desc] += 1

        nome_gruppo = f"• <b>{make} {model}</b>"
        if len(elementi) > 1:
            nome_gruppo += f" ({len(elementi)} unità):"
        else:
            nome_gruppo += ":"
        righe_messaggio.append(nome_gruppo)

        for desc, qta in conteggi_allestimenti.items():
            if len(elementi) > 1:
                righe_messaggio.append(f"  - {desc} (<b>{segno}{qta}</b>)")
            else:
                righe_messaggio.append(f"  - {desc}")
        righe_messaggio.append("")

    return righe_messaggio


def controlla_stock_nuove():
    session = requests.Session()
    session.headers.update(HEADERS_BASE)

    print("1. Recupero token CSRF...")
    csrf_token = ""
    try:
        r_page = session.get(URL_LOGIN, timeout=15)
        match = re.search(
            r'name="_csrf"\s+value="([^"]+)"', r_page.text
        ) or re.search(r'name="_csrf-frontend"\s+value="([^"]+)"', r_page.text)
        if match:
            csrf_token = match.group(1)
    except Exception as e:
        print(f"Errore caricamento pagina login: {e}")
        return

    print("2. Autenticazione su Quoter.it...")
    payload_login = {
        "LoginForm[username]": USERNAME,
        "LoginForm[password]": PASSWORD,
    }
    if csrf_token:
        payload_login["_csrf"] = csrf_token

    try:
        res_login = session.post(
            URL_LOGIN, data=payload_login, timeout=15, allow_redirects=True
        )
        print(f"Risposta login: HTTP {res_login.status_code}")
    except Exception as e:
        print(f"Errore invio login: {e}")
        return

    print("3. Navigazione sulla sezione Rinoleggio/Deal...")
    try:
        r_deal = session.get(
            URL_RINOLEGGIO, headers={"Referer": URL_LOGIN}, timeout=15
        )
        match_inner = re.search(
            r'meta\s+name="csrf-token"\s+content="([^"]+)"', r_deal.text
        )
        if match_inner:
            session.headers.update({"X-CSRF-Token": match_inner.group(1)})
    except Exception:
        pass

    print("4. Scaricamento stock report CSV...")
    vetture_attuali = {}

    headers_csv = {
        "Accept": "application/octet-stream",
        "Referer": URL_RINOLEGGIO,
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if csrf_token:
        headers_csv["X-CSRF-Token"] = csrf_token

    try:
        res_csv = session.get(
            URL_REPORT_STOCK, headers=headers_csv, timeout=60, allow_redirects=True
        )
        print(f"Risposta scaricamento CSV Stock: HTTP {res_csv.status_code}")

        if res_csv.status_code == 200 and len(res_csv.content) > 100:
            contenuto_csv = res_csv.content.decode("utf-8-sig", errors="ignore")
            f_csv = io.StringIO(contenuto_csv)

            try:
                dialetto = csv.Sniffer().sniff(contenuto_csv[:4000])
                reader = csv.DictReader(f_csv, dialect=dialetto)
            except Exception:
                reader = csv.DictReader(f_csv, delimiter=";")

            for row in reader:
                riga = {
                    str(k).strip().lower().replace(" ", "_"): str(v).strip()
                    for k, v in row.items()
                    if k
                }

                id_auto = (
                    riga.get("vehicleid")
                    or riga.get("id")
                    or riga.get("id_vettura")
                    or riga.get("chassisnumber")
                    or ""
                )
                if not id_auto:
                    continue

                make = riga.get("makename") or riga.get("marca") or ""
                model = riga.get("modelname") or riga.get("modello") or ""
                desc = riga.get("description") or f"{make} {model}".strip()

                vetture_attuali[id_auto] = {
                    "make": make,
                    "model": model,
                    "desc": desc,
                    "segment": riga.get("segment") or "",
                    "price": riga.get("prezzo_listino") or "",
                    "fuel": riga.get("alimentazione") or riga.get("fuel") or "",
                }
        else:
            print(f"Impossibile scaricare il CSV (Status: {res_csv.status_code})")

    except Exception as e:
        print(f"Errore durante lo scaricamento dello stock: {e}")

    tot_lette = len(vetture_attuali)
    print(f"Totale vetture lette dallo Stock Report: {tot_lette}")

    if not vetture_attuali:
        print("Nessuna vettura estratta dal file stock.")
        return

    # Gestione memoria e confronto
    vetture_salvate = {}
    primo_avvio = not os.path.exists(FILE_MEMORIA)

    if not primo_avvio:
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                vetture_salvate = json.load(f)
        except Exception:
            vetture_salvate = {}

    set_attuali = set(vetture_attuali.keys())
    set_salvate = set(vetture_salvate.keys())

    aggiunte_ids = set_attuali - set_salvate
    rimosse_ids = set_salvate - set_attuali

    # Salva sempre l'ultimo stato valido
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(vetture_attuali, f, indent=2)

    if primo_avvio:
        print(f"Primo avvio completato: memorizzate {tot_lette} vetture senza inviare notifiche.")
        invia_telegram(
            f"✅ <b>Monitor Stock Auto Nuove attivato!</b>\n"
            f"Memorizzate inizialmente <b>{tot_lette}</b> vetture.\n"
            f"Riceverai notifiche raggruppate per ogni nuova entrata o uscita."
        )
        return

    # Invio notifiche se ci sono variazioni
    if aggiunte_ids:
        print(f"Rilevati {len(aggiunte_ids)} nuovi ingressi. Invio report...")
        righe_in = genera_blocchi_raggruppati(
            aggiunte_ids, vetture_attuali, "NUOVI INGRESSI STOCK", "🟢", "+"
        )
        invia_messaggi_frazionati(righe_in)

    if rimosse_ids:
        print(f"Rilevate {len(rimosse_ids)} uscite dallo stock. Invio report...")
        righe_out = genera_blocchi_raggruppati(
            rimosse_ids, vetture_salvate, "USCITE DALLO STOCK", "🔴", "-"
        )
        invia_messaggi_frazionati(righe_out)

    if not aggiunte_ids and not rimosse_ids:
        print("Nessuna variazione di stock rilevata.")


if __name__ == "__main__":
    controlla_stock_nuove()
