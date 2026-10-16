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
URL_API_DETAIL = "https://quoter.it/proxy/deal/view?id={}"

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
    """Spezza l'invio in blocchi da 5 per rispettare i limiti di Telegram."""
    totale = len(lista_elementi)
    dimensione_blocco = 5

    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"<b>{titolo}</b> ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)


def is_opzionato(valore):
    """Verifica se il valore indica una posizione opzionata/occupata."""
    if valore is None:
        return False
    v = str(valore).strip().upper()
    return "OPZIONATO" in v or v in ["1", "TRUE", "ACTIVE", "SI", "SÌ", "OCCUPATO"]


def estrai_dettagli_vettura(session, auto_summary):
    """Ottiene le informazioni complete dell'auto cercando i campi stato_opzione1, stato_opzione2 e link2lifeimage."""
    id_auto = str(auto_summary.get("ID", "")).strip()

    # Dati di default ricavati dalla lista principale
    modello = auto_summary.get("NAME", "").strip()
    targa = auto_summary.get("LICENSEPLATE", "").strip()

    opt1_val = ""
    opt2_val = ""
    url_foto = ""

    # Tentativo di recuperare i dettagli estesi dall'API della singola vettura
    if id_auto:
        try:
            res_det = session.get(URL_API_DETAIL.format(id_auto), timeout=10)
            if res_det.status_code == 200:
                dettagli = res_det.json()
                if isinstance(dettagli, dict):
                    # Se i dati sono incapsulati in sotto-oggetti (es. "data" o "deal")
                    d_obj = dettagli.get("data") or dettagli.get("deal") or dettagli

                    opt1_val = (
                        d_obj.get("stato_opzione1")
                        or d_obj.get("stato_opzione_1")
                        or d_obj.get("STATO_OPZIONE1")
                        or ""
                    )
                    opt2_val = (
                        d_obj.get("stato_opzione2")
                        or d_obj.get("stato_opzione_2")
                        or d_obj.get("STATO_OPZIONE2")
                        or ""
                    )
                    url_foto = (
                        d_obj.get("link2lifeimage")
                        or d_obj.get("LINK2LIFEIMAGE")
                        or d_obj.get("link_image")
                        or ""
                    )
        except Exception:
            pass

    # Fallback ricerca nei campi diretti del summary se la chiamata di dettaglio non li contiene
    if not opt1_val and not opt2_val:
        opt1_val = (
            auto_summary.get("stato_opzione1")
            or auto_summary.get("stato_opzione_1")
            or ""
        )
        opt2_val = (
            auto_summary.get("stato_opzione2")
            or auto_summary.get("stato_opzione_2")
            or ""
        )

    if not url_foto:
        url_foto = (
            auto_summary.get("link2lifeimage")
            or auto_summary.get("LINK2LIFEIMAGE")
            or f"https://quoter.it/v2/deal/view?id={id_auto}"
        )

    opt1_active = is_opzionato(opt1_val)
    opt2_active = is_opzionato(opt2_val)

    num_opzioni = (1 if opt1_active else 0) + (1 if opt2_active else 0)

    desc_parti = []
    if modello:
        desc_parti.append(f"<b>{modello}</b>")
    if targa:
        desc_parti.append(f"Targa: {targa}")
    if id_auto:
        desc_parti.append(f"ID: {id_auto}")

    descrizione = " | ".join(desc_parti)

    return {
        "desc": descrizione,
        "options": num_opzioni,
        "url_foto": url_foto,
    }


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

    print("3. Estrazione elenco vetture...")
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
                id_auto = str(auto.get("ID", "")).strip()
                if not id_auto:
                    continue

                dettagli_vettura = estrai_dettagli_vettura(session, auto)
                vetture_attuali[id_auto] = dettagli_vettura
                trovate_in_pagina += 1

        print(f"   -> Pagina {pagina}: estratte {trovate_in_pagina} vetture con dettagli.")

        if trovate_in_pagina == 0 or pagina >= 10:
            break
        pagina += 1

    print(f"Totale vetture analizzate: {len(vetture_attuali)}")

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
        url_foto = dati["url_foto"]

        if id_auto not in vetture_salvate:
