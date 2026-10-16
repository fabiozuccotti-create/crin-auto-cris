import json
import os
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
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://quoter.it/v2/deal",
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


def calcola_opzioni(auto):
    """Estrae e conta il numero di opzioni associate alla vettura (max 2)."""
    # Verifica presenza campi list/count delle opzioni nel JSON
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

    payload_login = {
        "LoginForm[username]": USERNAME,
        "LoginForm[password]": PASSWORD,
    }

    try:
        res_login = session.post(URL_LOGIN, data=payload_login, timeout=15)
        if res_login.status_code != 200:
            print(f"Errore login HTTP {res_login.status_code}")
            return
    except Exception as e:
        print(f"Errore connessione login: {e}")
        return

    try:
        session.get(URL_RINOLEGGIO, timeout=15)
    except Exception:
        pass

    vetture_attuali = {}  # { chiave_auto: num_opzioni }
    pagina = 1

    while True:
        try:
            res_api = session.get(URL_API_BASE.format(pagina), timeout=15)
            if res_api.status_code != 200:
                break
            dati = res_api.json()
        except Exception:
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

        if trovate_in_pagina == 0 or pagina >= 10:
            break
        pagina += 1

    if not vetture_attuali:
        print("Nessuna vettura estratta.")
        return

    vetture_salvate = {}
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                dati_salvati = json.load(f)
                # Conversione retrocompatibile se il vecchio file era una lista
                if isinstance(dati_salvati, list):
                    vetture_salvate = {k: 0 for k in dati_salvati}
                elif isinstance(dati_salvati, dict):
                    vetture_salvate = dati_salvati
        except Exception:
            vetture_salvate = {}

    nuove_vetture = []
    variazioni_opzioni = []

    # Confronto stato attuale con memoria salvata
    for auto, opzioni_attuali in vetture_attuali.items():
        if auto not in vetture_salvate:
            nuove_vetture.append((auto, opzioni_attuali))
        else:
            opzioni_precedenti = vetture_salvate[auto]
            if opzioni_attuali != opzioni_precedenti:
                variazioni_opzioni.append(
                    (auto, opzioni_precedenti, opzioni_attuali)
                )

    # 1. Notifica Nuove Vetture
    if nuove_vetture:
        msg = f"🚨 NUOVE VETTURE RILEVATE ({len(nuove_vetture)}):\n\n"
        for auto, opt in nuove_vetture:
            msg += f"• {auto}\n  👉 Opzioni attuali: {opt}/2\n\n"
        invia_telegram(msg)

    # 2. Notifica Variazioni Opzioni
    if variazioni_opzioni:
        msg = f"🔄 VARIAZIONE OPZIONI RILEVATA ({len(variazioni_opzioni)}):\n\n"
        for auto, vecchie, nuove in variazioni_opzioni:
            msg += f"• {auto}\n  👉 Cambio opzioni: da {vecchie} a {nuove}\n\n"
        invia_telegram(msg)

    # Salva lo stato corrente
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(vetture_attuali, f, indent=2)

    if not nuove_vetture and not variazioni_opzioni:
        print("Nessuna variazione o nuova vettura rilevata.")


if __name__ == "__main__":
    controlla_sito()
