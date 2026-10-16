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


def invia_notifica_frazionata(titolo, lista_elementi):
    """Spezza l'invio in blocchi da 5 elementi per rispettare i limiti di Telegram."""
    totale = len(lista_elementi)
    dimensione_blocco = 5

    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"<b>{titolo}</b> ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)


def is_attivo(val):
    if val is None:
        return False
    v = str(val).strip().lower()
    if v in ["1", "true", "opzionata", "opzionato", "occupato", "active", "yes"]:
        return True
    if len(v) > 0 and v not in ["0", "false", "libero", "null", "none", "attesa", "", "[]", "{}"]:
        return True
    return False


def calcola_opzioni(auto):
    """Ispeziona tutti i campi possibili per 'Stato Opzione 1' e 'Stato Opzione 2'."""
    conteggio = 0

    # Ricerca dinamica delle chiavi per opzioni
    for k, v in auto.items():
        k_upper = str(k).upper()
        if "OPZI" in k_upper or "OPT" in k_upper:
            if is_attivo(v):
                if isinstance(v, list):
                    conteggio += len(v)
                else:
                    conteggio += 1

    # Controllo specifico strutture note
    if conteggio == 0:
        opt1 = any(is_attivo(auto.get(k)) for k in ["STATO OPZIONE 1", "STATO_OPZIONE_1", "OPTION_1", "option_1", "stato_opzione_1"])
        opt2 = any(is_attivo(auto.get(k)) for k in ["STATO OPZIONE 2", "STATO_OPZIONE_2", "OPTION_2", "option_2", "stato_opzione_2"])
        conteggio = (1 if opt1 else 0) + (1 if opt2 else 0)

    return min(conteggio, 2)


def get_pallini_opzioni(num_opzioni):
    if num_opzioni == 0:
        return "🟢🟢 (0 opzioni)"
    elif num_opzioni == 1:
        return "🔴🟢 (1 opzione)"
    else:
        return "🔴🔴 (2 opzioni)"


def controlla_sito():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("1. Recupero token CSRF...")
    try:
        r_page = session.get(URL_LOGIN, timeout=15)
        csrf_token = ""
        match = re.search(
            r'name="_csrf"\s+value="([^"]+)"', r_page.text
        ) or re.search(r'name="_csrf-frontend"\s+value="([^"]+)"', r_page.text)
        if match:
            csrf_token = match.group(1)
    except Exception as e:
        print(f"Errore caricamento pagina login: {e}")
        return

    print("2. Autenticazione...")
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

    print("3. Estrazione vetture...")
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

        # Debug: Stampa le chiavi della prima vettura per identificare i nomi esatti delle opzioni nel JSON
        if pagina == 1 and len(lista_veicoli) > 0:
            print("CHIAVI ESEMPIO VETTURA API:", list(lista_veicoli[0].keys()))

        trovate_in_pagina = 0
        for auto in lista_veicoli:
            if isinstance(auto, dict):
                id_auto = str(auto.get("ID", "")).strip()
                if not id_auto:
                    continue

                modello = auto.get("NAME", "").strip()
                targa = auto.get("LICENSEPLATE", "").strip()

                desc_parti = []
                if modello:
                    desc_parti.append(f"<b>{modello}</b>")
                if targa:
                    desc_parti.append(f"Targa: {targa}")
                desc_parti.append(f"ID: {id_auto}")

                descrizione = " | ".join(desc_parti)
                num_opzioni = calcola_opzioni(auto)

                vetture_attuali[id_auto] = {
                    "desc": descrizione,
                    "options": num_opzioni,
                }
                trovate_in_pagina += 1

        print(f"   -> Pagina {pagina}: estratte {trovate_in_pagina} vetture.")

        if trovate_in_pagina == 0 or pagina >= 10:
            break
        pagina += 1

    print(f"Totale vetture univoche lette: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura trovata.")
        return

    vetture_salvate = {}
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                dati_salvati = json.load(f)
                if isinstance(dati_salvati, dict):
                    vetture_salvate = dati_salvati
        except Exception:
            vetture_salvate = {}

    nuove_vetture_lista = []
    variazioni_opzioni_lista = []

    for id_auto, dati in vetture_attuali.items():
        desc = dati["desc"]
        opt_attuali = dati["options"]

        if id_auto not in vetture_salvate:
            nuove_vetture_lista.append((id_auto, desc, opt_attuali))
        else:
            opt_precedenti = vetture_salvate[id_auto].get("options", 0)
            if opt_attuali != opt_precedenti:
                variazioni_opzioni_lista.append(
                    (id_auto, desc, opt_precedenti, opt_attuali)
                )

    # Ordinamento: 0 opzioni (🟢🟢) per prime, poi 1 (🔴🟢), poi 2 (🔴🔴)
    nuove_vetture_lista.sort(key=lambda x: x[2])
    variazioni_opzioni_lista.sort(key=lambda x: x[3])

    nuove_vetture_testo = []
    for _, desc, opt in nuove_vetture_lista:
        pallini = get_pallini_opzioni(opt)
        nuove_vetture_testo.append(f"• {desc}\n  👉 Stato: {pallini}")

    variazioni_opzioni_testo = []
    for _, desc, opt_vecchie, opt_nuove in variazioni_opzioni_lista:
        pallini_vecchi = get_pallini_opzioni(opt_vecchie)
        pallini_nuovi = get_pallini_opzioni(opt_nuove)
        variazioni_opzioni_testo.append(
            f"• {desc}\n  👉 Variazione: da {pallini_vecchi} a {pallini_nuovi}"
        )

    if nuove_vetture_testo:
        invia_notifica_frazionata("🚨 NUOVE VETTURE RILEVATE", nuove_vetture_testo)

    if variazioni_opzioni_testo:
        invia_notifica_frazionata(
            "🔄 VARIAZIONE OPZIONI RILEVATA", variazioni_opzioni_testo
        )

    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(vetture_attuali, f, indent=2)

    if not nuove_vetture_testo and not variazioni_opzioni_testo:
        print("Nessun nuovo inserimento o variazione opzioni.")


if __name__ == "__main__":
    controlla_sito()
