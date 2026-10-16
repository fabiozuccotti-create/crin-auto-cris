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
URL_API_BASE = "https://quoter.it/proxy/deal/list?action=leaseafter&target=list&page={}&refresh=false&filters=%7B%22generic%22%3Anull%7D"
URL_EXPORT_CSV = "https://quoter.it/v2/deal/export?action=leaseafter"

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
    """Spezza l'invio in blocchi da 5 per non superare i limiti di Telegram."""
    totale = len(lista_elementi)
    dimensione_blocco = 5

    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"<b>{titolo}</b> ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)


def is_opzione_occupata(valore):
    """Controlla se lo stato equivale a OPZIONATO."""
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

    # TENTATIVO A: Lettura da esportazione CSV (contiene stato_opzione1, stato_opzione2, link2lifeimage)
    print("3. Lettura dati vetture da esportazione CSV...")
    try:
        res_csv = session.get(URL_EXPORT_CSV, timeout=30)
        if res_csv.status_code == 200 and len(res_csv.content) > 100:
            contenuto_csv = res_csv.content.decode("utf-8-sig", errors="ignore")
            f_csv = io.StringIO(contenuto_csv)
            dialetto = csv.Sniffer().sniff(contenuto_csv[:2000])
            reader = csv.DictReader(f_csv, dialect=dialetto)

            for row in reader:
                riga = {
                    str(k).strip().lower().replace(" ", "_"): str(v).strip()
                    for k, v in row.items()
                    if k
                }

                id_auto = riga.get("id") or riga.get("id_vettura") or riga.get("codice") or ""
                modello = riga.get("modello") or riga.get("name") or riga.get("descrizione") or ""
                targa = riga.get("targa") or riga.get("licenseplate") or ""

                if not id_auto and not targa:
                    continue

                chiave_id = id_auto if id_auto else targa

                opt1_val = riga.get("stato_opzione1") or riga.get("stato_opzione_1") or ""
                opt2_val = riga.get("stato_opzione2") or riga.get("stato_opzione_2") or ""
                url_foto = riga.get("link2lifeimage") or riga.get("link_image") or ""

                opt1_active = is_opzione_occupata(opt1_val)
                opt2_active = is_opzione_occupata(opt2_val)

                num_opzioni = (1 if opt1_active else 0) + (1 if opt2_active else 0)

                desc_parti = []
                if modello:
                    desc_parti.append(f"<b>{modello}</b>")
                if targa:
                    desc_parti.append(f"Targa: {targa}")
                if id_auto:
                    desc_parti.append(f"ID: {id_auto}")

                descrizione = " | ".join(desc_parti)

                vetture_attuali[chiave_id] = {
                    "desc": descrizione,
                    "options": num_opzioni,
                    "url_foto": url_foto,
                }
    except Exception as e:
        print(f"Avviso export CSV: {e}")

    # TENTATIVO B: Scansione Pagine API (se il CSV non è disponibile)
    if not vetture_attuali:
        print("3b. Lettura dati vetture via API pagine...")
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
                for k in ["data", "items", "deals", "list", "rows", "results", "stock"]:
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
                    # Normalizza tutti i nomi delle chiavi in minuscolo
                    auto_norm = {str(k).lower().replace(" ", "_"): v for k, v in auto.items()}

                    id_auto = str(auto_norm.get("id", "")).strip()
                    if not id_auto:
                        continue

                    modello = str(auto_norm.get("name", "")).strip()
                    targa = str(auto_norm.get("licenseplate", "")).strip()

                    opt1_val = auto_norm.get("stato_opzione1") or auto_norm.get("stato_opzione_1") or auto_norm.get("option_1_status") or ""
                    opt2_val = auto_norm.get("stato_opzione2") or auto_norm.get("stato_opzione_2") or auto_norm.get("option_2_status") or ""
                    url_foto = auto_norm.get("link2lifeimage") or auto_norm.get("link_image") or f"https://quoter.it/v2/deal/view?id={id_auto}"

                    num_opzioni = (1 if is_opzione_occupata(opt1_val) else 0) + (1 if is_opzione_occupata(opt2_val) else 0)

                    desc_parti = []
                    if modello:
                        desc_parti.append(f"<b>{modello}</b>")
                    if targa:
                        desc_parti.append(f"Targa: {targa}")
                    desc_parti.append(f"ID: {id_auto}")

                    descrizione = " | ".join(desc_parti)

                    vetture_attuali[id_auto] = {
                        "desc": descrizione,
                        "options": num_opzioni,
                        "url_foto": str(url_foto),
                    }
                    trovate_in_pagina += 1

            if trovate_in_pagina == 0 or pagina >= 10:
                break
            pagina += 1

    print(f"Totale vetture lette: {len(vetture_attuali)}")

    if not vetture_attuali:
        print("Nessuna vettura trovata.")
        return

    vetture_salvate = {}
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                dati_salvati = json.load(f)
                if isinstance(dati_salvati, dict):
                    vetture_salvati = dati_salvati
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

    # Ordinamento: per prime 0 opzioni (🟢🟢), poi 1 (🔴🟢), infine 2 (🔴🔴)
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
