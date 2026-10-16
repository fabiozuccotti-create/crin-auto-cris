import json
import os
import re
import requests

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
CHAT_ID = os.environ.get("CHAT_ID")
USERNAME = os.environ.get("QUOTER_USER")
PASSWORD = os.environ.get("QUOTER_PASS")

URL_LOGIN = "https://quoter.it/site/login"
URL_RINOLEGGIO = "https://quoter.it/v2/deal"
URL_API_BASE = "https://quoter.it/proxy/deal/list?action=leaseafter&target=list&page={}&refresh=false&filters=%7B%22generic%22%3Anull%7D"

FILE_MEMORIA = "vetture_salvate.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}


def invia_telegram(messaggio):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": messaggio}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print(f"Errore Telegram: {r.text}")
    except Exception as e:
        print(f"Errore connessione Telegram: {e}")


def invia_notifica_frazionata(titolo, lista_elementi):
    """Spezza l'invio dei messaggi in blocchi da 5 per evitare il limite di Telegram."""
    totale = len(lista_elementi)
    dimensione_blocco = 5

    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"{titolo} ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)


def calcola_opzioni(auto):
    """Estrae e conta le opzioni della vettura (massimo 2)."""
    if "options" in auto and isinstance(auto["options"], list):
        return min(len(auto["options"]), 2)
    if "OPTIONS_COUNT" in auto:
        try:
            return min(int(auto["OPTIONS_COUNT"]), 2)
        except (ValueError, TypeError):
            pass
    if "OPTIONS" in auto and isinstance(auto["OPTIONS"], list):
        return min(len(auto["OPTIONS"]), 2)
    return 0


def controlla_sito():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("1. Richiesta pagina di login per recupero CSRF token...")
    try:
        r_page = session.get(URL_LOGIN, timeout=15)
        csrf_token = ""
        match = re.search(
            r'name="_csrf"\s+value="([^"]+)"', r_page.text
        ) or re.search(r'name="_csrf-frontend"\s+value="([^"]+)"', r_page.text)
        if match:
            csrf_token = match.group(1)
    except Exception as e:
        print(f"Errore caricamento login: {e}")
        return

    print("2. Invio credenziali di login...")
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

    print("3. Inizializzazione sessione Rinoleggio...")
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://quoter.it/v2/deal",
        }
    )

    try:
        session.get(URL_RINOLEGGIO, timeout=15)
    except Exception:
        pass

    vetture_attuali = {}
    pagina = 1

    print("4. Estrazione vetture dalle pagine API...")
    while True:
        try:
            res_api = session.get(URL_API_BASE.format(pagina), timeout=15)
            if res_api.status_code != 200:
                print(f"Fine pagine o errore HTTP {res_api.status_code}")
                break
            dati = res_api.json()
        except Exception as e:
            print(f"Interruzione lettura JSON a pagina {pagina}: {e}")
            break

        lista_veicoli = []
        if isinstance(dati, dict):
            for k in [
                "data",
                "items",
                "deals",
                "list",
                "rows",
                "results",
                "stock",
            ]:
                if k in dati and isinstance(dati[k], list):
                    lista_veicoli = dati[k]
                    break
            if not lista_veicoli:
                for k, v in dati.items():
                    if isinstance(v, list) and len(v) > 0:
                        lista_veicoli = v
                        break
        elif isinstance(dati, list):
            lista_veicoli = dati

        if not lista_veicoli:
            break

        trovate_in_pagina = 0
        for auto in lista_veicoli:
            if isinstance(auto, dict):
                modello = auto.get("NAME", "").strip()
                targa = auto.get("LICENSEPLATE", "").strip()
                id_auto = str(auto.get("ID", "")).strip()

                info = " | ".join(
                    filter(
                        None,
                        [
                            modello,
                            f"Targa: {targa}" if targa else "",
                            f"ID: {id_auto}" if id_auto else "",
                        ],
                    )
                )
                chiave = info if info else f"Vettura ID: {id_auto}"
                num_opzioni = calcola_opzioni(auto)

                vetture_attuali[chiave] = num_opzioni
                trovate_in_pagina += 1

        print(f"   -> Pagina {pagina}: estratte {trovate_in_pagina} vetture.")

        if trovate_in_pagina == 0 or pagina >= 10:
            break
        pagina += 1

    print(f"Totale vetture trovate sul sito: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura trovata.")
        return

    vetture_salvate = {}
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                dati_salvati = json.load(f)
                if isinstance(dati_salvati, list):
                    vetture_salvate = {k: 0 for k in dati_salvati}
                elif isinstance(dati_salvati, dict):
                    vetture_salvate = dati_salvati
        except Exception:
            vetture_salvate = {}

    nuove_vetture_testo = []
    variazioni_opzioni_testo = []

    for auto, opzioni_attuali in vetture_attuali.items():
        if auto not in vetture_salvate:
            nuove_vetture_testo.append(f"• {auto}\n  👉 Opzioni: {opzioni_attuali}/2")
        else:
            opzioni_precedenti = vetture_salvate[auto]
            if opzioni_attuali != opzioni_precedenti:
                variazioni_opzioni_testo.append(
                    f"• {auto}\n  👉 Cambio opzioni: da {opzioni_precedenti} a {opzioni_attuali}"
                )

    # 1. Notifica Nuove Vetture
    if nuove_vetture_testo:
        invia_notifica_frazionata("🚨 NUOVE VETTURE RILEVATE", nuove_vetture_testo)

    # 2. Notifica Variazioni Opzioni
    if variazioni_opzioni_testo:
        invia_notifica_frazionata("🔄 VARIAZIONE OPZIONI RILEVATA", variazioni_opzioni_testo)

    # Salvataggio dello stato
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(vetture_attuali, f, indent=2)

    if not nuove_vetture_testo and not variazioni_opzioni_testo:
        print("Nessun nuovo inserimento o cambio opzioni.")


if __name__ == "__main__":
    controlla_sito()
