import os
import json
import requests
import re

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
CHAT_ID = os.environ.get("CHAT_ID")
USERNAME = os.environ.get("QUOTER_USER")
PASSWORD = os.environ.get("QUOTER_PASS")

URL_LOGIN = "https://quoter.it/site/login"
URL_RINOLEGGIO = "https://quoter.it/v2/deal"
URL_API_LIST = "https://quoter.it/proxy/deal/list"

FILE_MEMORIA = "vetture_salvate.json"

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://quoter.it/v2/deal",
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

def controlla_sito():
    session = requests.Session()
    session.headers.update(HEADERS_BASE)

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

    print("3. Inizializzazione sessione Rinoleggio...")
    try:
        session.get(URL_RINOLEGGIO, timeout=15)
    except Exception:
        pass

    print("4. Recupero elenco vetture tramite API JSON...")
    vetture_attuali = {}
    
    headers_api = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    page = 1
    while True:
        params = {
            "action": "leaseafter",
            "target": "list",
            "page": page,
            "refresh": "false",
            "filters": '{"generic":null}',
        }

        try:
            res_api = session.get(URL_API_LIST, headers=headers_api, params=params, timeout=15)
            print(f"Pagina {page} API: HTTP {res_api.status_code}")

            if res_api.status_code != 200:
                print(f"Errore risposta API sulla pagina {page}")
                break

            data_json = res_api.json()
            
            # Estrazione array elementi
            items = []
            if isinstance(data_json, list):
                items = data_json
            elif isinstance(data_json, dict):
                items = data_json.get("data") or data_json.get("items") or data_json.get("rows") or []

            if not items:
                break

            for item in items:
                id_auto = str(item.get("id") or item.get("deal_id") or item.get("code") or "")
                targa = str(item.get("licenseplate") or item.get("targa") or "")
                modello = str(item.get("description") or item.get("modelname") or item.get("modello") or "")
                marca = str(item.get("makename") or item.get("marca") or "")

                if marca and modello and marca.lower() not in modello.lower():
                    modello_completo = f"{marca} {modello}"
                else:
                    modello_completo = modello

                chiave_id = id_auto if id_auto else targa
                if not chiave_id:
                    continue

                opt1_val = str(item.get("status1") or item.get("stato_opzione1") or item.get("option1") or "")
                opt2_val = str(item.get("status2") or item.get("stato_opzione2") or item.get("option2") or "")
                url_foto = str(item.get("link2lifeimage") or item.get("image_link") or item.get("image") or "")

                num_opzioni = (1 if is_opzionato(opt1_val) else 0) + (1 if is_opzionato(opt2_val) else 0)

                desc_parti = []
                if modello_completo:
                    desc_parti.append(f"<b>{modello_completo}</b>")
                if targa:
                    desc_parti.append(f"Targa: {targa}")
                if id_auto:
                    desc_parti.append(f"ID: {id_auto}")

                vetture_attuali[chiave_id] = {
                    "desc": " | ".join(desc_parti),
                    "options": num_opzioni,
                    "url_foto": url_foto,
                }

            # Se restituisce meno elementi del limite di pagina (es. 20/50), abbiamo finito le pagine
            if len(items) < 10:
                break

            page += 1

        except Exception as e:
            print(f"Errore durante l'estrazione JSON: {e}")
            break

    print(f"Totale vetture trovate: {len(vetture_attuali)}")

    # Gestione file memoria per Git
    if not vetture_attuali:
        print("Nessuna vettura trovata.")
        if not os.path.exists(FILE_MEMORIA):
            with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
                json.dump({}, f)
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
