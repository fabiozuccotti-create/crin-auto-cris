import csv
import io
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
URL_PROXY_LIST = "https://quoter.it/proxy/deal/list"
URL_PROXY_CSV = "https://quoter.it/proxy/deal/list?target=report&action=leaseafter"

FILE_MEMORIA = "vetture_salvate.json"

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
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
    totale = len(lista_elementi)
    dimensione_blocco = 5
    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"<b>{titolo}</b> ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)


def is_opzionato(valore):
    if not valore:
        return False
    v = str(valore).strip().upper()
    return "OPZIONATO" in v or v in ["1", "TRUE", "ACTIVE", "SI", "SÌ", "OCCUPATO"]


def get_pallini_opzioni(num_opzioni):
    if num_opzioni == 0:
        return "🟢🟢 (0 opzioni)"
    elif num_opzioni == 1:
        return "🔴🟢 (1 opzione)"
    else:
        return "🔴🔴 (2 opzioni)"


def estrai_modello_da_riga(riga):
    if riga.get("description"):
        return riga["description"]
    make = riga.get("makename") or riga.get("marca") or ""
    model = riga.get("modelname") or riga.get("modello") or ""
    if make or model:
        return f"{make} {model}".strip()
    for k in ["modello", "name", "descrizione", "veicolo"]:
        if riga.get(k):
            return riga[k]
    return ""


def controlla_sito():
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
            print(f"Token CSRF trovato: {csrf_token[:10]}...")
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

    # Se presente, aggiorna le intestazioni con il token CSRF per sbloccare le API proxy
    if csrf_token:
        session.headers.update({"X-CSRF-Token": csrf_token})

    print("3. Navigazione sulla pagina Rinoleggio...")
    try:
        r_v2 = session.get(URL_RINOLEGGIO, headers={"Referer": URL_LOGIN}, timeout=15)
        # Cerca un eventuale nuovo CSRF token generato nella pagina interna
        match_inner = re.search(r'meta\s+name="csrf-token"\s+content="([^"]+)"', r_v2.text)
        if match_inner:
            inner_csrf = match_inner.group(1)
            session.headers.update({"X-CSRF-Token": inner_csrf})
            print(f"Token CSRF interno aggiornato: {inner_csrf[:10]}...")
    except Exception as e:
        print(f"Avviso navigazione Rinoleggio: {e}")

    vetture_attuali = {}

    # Tentativo 1: API JSON con header AJAX e CSRF
    print("4a. Recupero vetture via API JSON...")
    headers_api = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": URL_RINOLEGGIO,
        "X-Requested-With": "XMLHttpRequest",
    }

    params_api = {
        "action": "leaseafter",
        "target": "list",
        "page": 1,
        "refresh": "false",
        "filters": '{"generic":null}',
    }

    try:
        res_api = session.get(URL_PROXY_LIST, headers=headers_api, params=params_api, timeout=15)
        print(f"Risposta API Proxy JSON: HTTP {res_api.status_code}")

        if res_api.status_code == 200:
            data = res_api.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                id_auto = str(item.get("id") or item.get("deal_id") or item.get("code") or "")
                targa = str(item.get("licenseplate") or item.get("targa") or "")
                modello = str(item.get("description") or item.get("modelname") or item.get("modello") or "")
                marca = str(item.get("makename") or item.get("marca") or "")

                desc_completa = f"{marca} {modello}".strip() if marca and marca.lower() not in modello.lower() else modello
                chiave = id_auto if id_auto else targa
                if not chiave:
                    continue

                opt1 = is_opzionato(str(item.get("status1") or item.get("option1") or ""))
                opt2 = is_opzionato(str(item.get("status2") or item.get("option2") or ""))
                num_opzioni = (1 if opt1 else 0) + (1 if opt2 else 0)

                vetture_attuali[chiave] = {
                    "desc": f"<b>{desc_completa}</b> | Targa: {targa} | ID: {id_auto}",
                    "options": num_opzioni,
                    "url_foto": str(item.get("link2lifeimage") or item.get("image") or ""),
                }
    except Exception as e:
        print(f"Errore chiamata API JSON: {e}")

    # Tentativo 2: Scaricamento CSV con CSRF abilitato se l'API non restituisce dati
    if not vetture_attuali:
        print("4b. Fallback scaricamento CSV...")
        headers_csv = {
            "Accept": "application/octet-stream",
            "Referer": URL_RINOLEGGIO,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            res_csv = session.get(URL_PROXY_CSV, headers=headers_csv, timeout=20)
            print(f"Risposta scaricamento CSV: HTTP {res_csv.status_code}")

            if res_csv.status_code == 200 and len(res_csv.content) > 50:
                contenuto_csv = res_csv.content.decode("utf-8-sig", errors="ignore")
                f_csv = io.StringIO(contenuto_csv)
                dialetto = csv.Sniffer().sniff(contenuto_csv[:2000])
                reader = csv.DictReader(f_csv, dialect=dialetto)
                for row in reader:
                    riga = {str(k).strip().lower().replace(" ", "_"): str(v).strip() for k, v in row.items() if k}
                    id_auto = riga.get("id") or riga.get("deal_id") or ""
                    targa = riga.get("targa") or riga.get("licenseplate") or ""
                    modello = estrai_modello_da_riga(riga)
                    chiave = id_auto if id_auto else targa
                    if not chiave:
                        continue
                    num_opzioni = (1 if is_opzionato(riga.get("stato_opzione1")) else 0) + (1 if is_opzionato(riga.get("stato_opzione2")) else 0)
                    vetture_attuali[chiave] = {
                        "desc": f"<b>{modello}</b> | Targa: {targa}",
                        "options": num_opzioni,
                        "url_foto": riga.get("link2lifeimage", ""),
                    }
        except Exception as e:
            print(f"Errore scaricamento CSV: {e}")

    print(f"Totale vetture lette dal server: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura estratta dal server.")
        if not os.path.exists(FILE_MEMORIA):
            with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
                json.dump({}, f)
        return

    vetture_salvate = {}
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                vetture_salvate = json.load(f)
        except Exception:
            vetture_salvate = {}

    nuove_vetture_lista = []
    variazioni_opzioni_lista = []

    for id_auto, dati in vetture_attuali.items():
        desc = dati["desc"]
        opt_attuali = dati["options"]
        url_foto = dati["url_foto"]

        if id_auto not in vetture_salvate:
            nuove_vetture_lista.append((id_auto, desc, opt_attuali, url_foto))
        else:
            opt_precedenti = vetture_salvate[id_auto].get("options", 0)
            if opt_attuali != opt_precedenti:
                variazioni_opzioni_lista.append(
                    (id_auto, desc, opt_precedenti, opt_attuali, url_foto)
                )

    nuove_vetture_lista.sort(key=lambda x: x[2])
    variazioni_opzioni_lista.sort(key=lambda x: x[3])

    nuove_vetture_testo = []
    for _, desc, opt, url_f in nuove_vetture_lista:
        pallini = get_pallini_opzioni(opt)
        riga_msg = f"• {desc}\n  👉 Stato: {pallini}"
        if url_f and str(url_f).startswith("http"):
            riga_msg += f'\n  📷 <a href="{url_f}">Vedi Foto</a>'
        nuove_vetture_testo.append(riga_msg)

    variazioni_opzioni_testo = []
    for _, desc, opt_v, opt_n, url_f in variazioni_opzioni_lista:
        p_vecchi = get_pallini_opzioni(opt_v)
        p_nuovi = get_pallini_opzioni(opt_n)
        riga_msg = f"• {desc}\n  👉 Variazione: da {p_vecchi} a {p_nuovi}"
        if url_f and str(url_f).startswith("http"):
            riga_msg += f'\n  📷 <a href="{url_f}">Vedi Foto</a>'
        variazioni_opzioni_testo.append(riga_msg)

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
