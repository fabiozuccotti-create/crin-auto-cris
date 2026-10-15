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


def invia_notifica_frazionata(nuove_vetture):
    lista_auto = list(nuove_vetture)
    totale = len(lista_auto)
    dimensione_blocco = 5

    for i in range(0, totale, dimensione_blocco):
        blocco = lista_auto[i : i + dimensione_blocco]
        msg = f"🚨 RINOLEGGIO QUOTER: NUOVE VETTURE ({i+1}-{min(i+dimensione_blocco, totale)} di {totale})\n\n"
        for v in blocco:
            msg += f"• {v}\n\n"
        invia_telegram(msg)


def controlla_sito():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("1. Login in corso su Quoter.it...")
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

    vetture_attuali = set()
    pagina = 1

    print("2. Scaricamento pagine vetture...")
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
                vetture_attuali.add(info if info else f"Vettura ID: {id_auto}")
                trovate_in_pagina += 1

        print(f"   -> Pagina {pagina}: trovate {trovate_in_pagina} vetture.")

        if trovate_in_pagina == 0 or pagina >= 10:
            break

        pagina += 1

    print(f"Totale vetture estratte: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura estratta.")
        return

    vetture_salvate = set()
    if os.path.exists(FILE_MEMORIA):
        with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
            vetture_salvate = set(json.load(f))

    nuove = vetture_attuali - vetture_salvate

    if nuove:
        print(f"Trovate {len(nuove)} nuove vetture! Invio notifiche...")
        invia_notifica_frazionata(nuove)
        with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
            json.dump(list(vetture_attuali.union(vetture_salvate)), f)
        print("Notifiche inviate su Telegram!")
    else:
        print(
            "Nessun nuovo inserimento in Rinoleggio rispetto all'ultimo controllo."
        )


if __name__ == "__main__":
    controlla_sito()
