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
# Endpoint API nativo di Quoter usato dalla tabella web
URL_API_DEALS = "https://quoter.it/proxy/deal/list?target=deal&action=leaseafter"

FILE_MEMORIA = "vetture_salvate.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://quoter.it/v2/deal",
    "X-Requested-With": "XMLHttpRequest",
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

    print("3. Navigazione e consolidamento sessione Rinoleggio...")
    res_rinoleggio = session.get(URL_RINOLEGGIO, timeout=15)

    vetture_attuali = {}

    # Tentativo A: Lettura via API JSON
    print("4a. Recupero dati via API JSON...")
    try:
        res_api = session.get(URL_API_DEALS, timeout=20)
        print(f"Risposta API: HTTP {res_api.status_code}")

        if res_api.status_code == 200:
            dati = res_api.json()
            # Gestione risposta sia come lista sia come oggetto dict
            lista_deals = dati.get("data", dati) if isinstance(dati, dict) else dati

            if isinstance(lista_deals, list):
                for item in lista_deals:
                    id_auto = str(item.get("id") or item.get("deal_id") or "")
                    targa = str(item.get("licenseplate") or item.get("targa") or "")
                    modello = str(
                        item.get("description")
                        or item.get("modelname")
                        or item.get("modello")
                        or ""
                    )
                    make = str(item.get("makename") or item.get("marca") or "")

                    if make and modello and make not in modello:
                        modello_completo = f"{make} {modello}"
                    else:
                        modello_completo = modello

                    chiave_id = id_auto if id_auto else targa
                    if not chiave_id:
                        continue

                    opt1_val = str(item.get("status1") or item.get("stato_opzione1") or "")
                    opt2_val = str(item.get("status2") or item.get("stato_opzione2") or "")
                    url_foto = str(item.get("link2lifeimage") or item.get("image_link") or "")

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
    except Exception as e:
        print(f"Chiamata API non riuscita o risposta non JSON: {e}")

    # Tentativo B: Fallback estrazione JSON da HTML
    if not vetture_attuali:
        print("4b. Fallback: Estrazione dati dal sorgente HTML...")
        html = res_rinoleggio.text
        blocchi_json = re.findall(r"var\_deals\s*=\s*(\[.*?\]);", html, re.DOTALL) or re.findall(
            r'data-deals=\'([^\']+)\'', html
        )

        if blocchi_json:
            try:
                dati = json.loads(blocchi_json[0])
                for item in dati:
                    id_auto = str(item.get("id") or "")
                    targa = str(item.get("licenseplate") or item.get("targa") or "")
                    modello = str(item.get("description") or item.get("modelname") or "")
                    chiave_id = id_auto if id_auto else targa
                    if not chiave_id:
                        continue

                    num_opzioni = (1 if is_opzionato(str(item.get("status1"))) else 0) + (
                        1 if is_opzionato(str(item.get("status2"))) else 0
                    )
                    url_foto = str(item.get("link2lifeimage") or "")

                    desc_parti = []
                    if modello:
                        desc_parti.append(f"<b>{modello}</b>")
                    if targa:
                        desc_parti.append(f"Targa: {targa}")

                    vetture_attuali[chiave_id] = {
                        "desc": " | ".join(desc_parti),
                        "options": num_opzioni,
                        "url_foto": url_foto,
                    }
            except Exception as e:
                print(f"Errore parsing HTML fallback: {e}")

    print(f"Totale vetture lette: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura trovata su Quoter.it.")
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
