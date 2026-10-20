import os
import json
import requests
import re
from bs4 import BeautifulSoup

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
CHAT_ID = os.environ.get("CHAT_ID")
USERNAME = os.environ.get("QUOTER_USER")
PASSWORD = os.environ.get("QUOTER_PASS")

URL_LOGIN = "https://quoter.it/site/login"
URL_RINOLEGGIO = "https://quoter.it/v2/deal"

FILE_MEMORIA = "vetture_salvate.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
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
    totale = len(lista_elementi)
    dimensione_blocco = 5
    for i in range(0, totale, dimensione_blocco):
        blocco = lista_elementi[i : i + dimensione_blocco]
        msg = f"<b>{titolo}</b> ({i+1}-{min(i+dimensione_blocco, totale)} di {totale}):\n\n"
        for voce in blocco:
            msg += f"{voce}\n\n"
        invia_telegram(msg)

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

    print("3. Scaricamento pagina HTML Rinoleggio...")
    res_page = session.get(URL_RINOLEGGIO, timeout=20)
    print(f"Risposta pagina Rinoleggio: HTTP {res_page.status_code}")

    vetture_attuali = {}

    if res_page.status_code == 200:
        html = res_page.text
        
        # Tentativo A: Cerca se i dati delle vetture sono salvati come JSON dentro lo script JS della pagina
        match_json = re.search(r'var\s+deals\s*=\s*(\[.*?\]);', html, re.DOTALL) or re.search(r'data-deals=\'([^\']+)\'', html)
        if match_json:
            try:
                data = json.loads(match_json.group(1))
                for item in data:
                    id_auto = str(item.get("id") or item.get("deal_id") or "")
                    targa = str(item.get("licenseplate") or item.get("targa") or "")
                    modello = str(item.get("description") or item.get("modelname") or "")
                    chiave = id_auto if id_auto else targa
                    if not chiave:
                        continue
                    
                    num_opzioni = 0
                    if "OPZIONATO" in str(item.get("status1", "")).upper():
                        num_opzioni += 1
                    if "OPZIONATO" in str(item.get("status2", "")).upper():
                        num_opzioni += 1

                    vetture_attuali[chiave] = {
                        "desc": f"<b>{modello}</b> | Targa: {targa} | ID: {id_auto}",
                        "options": num_opzioni,
                        "url_foto": str(item.get("link2lifeimage") or "")
                    }
            except Exception as e:
                print(f"Errore parsing JSON interno: {e}")

        # Tentativo B: Parsing diretto della tabella HTML tramite BeautifulSoup
        if not vetture_attuali:
            soup = BeautifulSoup(html, "html.parser")
            righe = soup.find_all("tr")
            for riga in righe:
                celle = riga.find_all("td")
                if len(celle) < 3:
                    continue
                
                testo = " ".join([c.get_text(strip=True) for c in celle])
                if len(testo) < 10:
                    continue
                
                img = riga.find("img")
                url_foto = img["src"] if img and "src" in img.attrs else ""

                num_opzioni = testo.upper().count("OPZIONATO")
                
                chiave = str(hash(testo[:60]))
                vetture_attuali[chiave] = {
                    "desc": f"<b>{testo[:80]}</b>",
                    "options": min(num_opzioni, 2),
                    "url_foto": url_foto
                }

    print(f"Totale vetture estratte dall'HTML: {len(vetture_attuali)}")

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
