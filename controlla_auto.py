import csv
import io
import json
import os
import requests
from playwright.sync_api import sync_playwright

TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
CHAT_ID = os.environ.get("CHAT_ID")
USERNAME = os.environ.get("QUOTER_USER")
PASSWORD = os.environ.get("QUOTER_PASS")

URL_LOGIN = "https://quoter.it/site/login"
URL_RINOLEGGIO = "https://quoter.it/v2/deal"
FILE_MEMORIA = "vetture_salvate.json"


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


def scarica_csv_con_browser():
    contenuto_csv = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print("1. Apertura pagina di Login...")
        page.goto(URL_LOGIN, wait_until="networkidle")

        print("2. Esecuzione Login...")
        page.fill('input[name="LoginForm[username]"]', USERNAME)
        page.fill('input[name="LoginForm[password]"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        print("3. Navigazione su Rinoleggio...")
        page.goto(URL_RINOLEGGIO, wait_until="networkidle")
        page.wait_for_timeout(3000)

        print("4. Clic su Export CSV...")
        try:
            with page.expect_download(timeout=30000) as download_info:
                # Cerca e clicca il pulsante di esportazione nella pagina
                btn_export = page.locator('a[href*="target=report"], button:has-text("CSV"), a:has-text("Export"), .btn-export').first
                btn_export.click()

            download = download_info.value
            temp_path = download.path()
            with open(temp_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                contenuto_csv = f.read()
            print("CSV scaricato con successo tramite browser!")
        except Exception as e:
            print(f"Errore durante il download via browser: {e}")

        browser.close()
    return contenuto_csv


def controlla_sito():
    contenuto_csv = scarica_csv_con_browser()
    vetture_attuali = {}

    if contenuto_csv and len(contenuto_csv) > 50:
        f_csv = io.StringIO(contenuto_csv)
        try:
            dialetto = csv.Sniffer().sniff(contenuto_csv[:2000])
            reader = csv.DictReader(f_csv, dialect=dialetto)
        except Exception:
            reader = csv.DictReader(f_csv)

        for row in reader:
            riga = {
                str(k).strip().lower().replace(" ", "_"): str(v).strip()
                for k, v in row.items()
                if k
            }

            id_auto = (
                riga.get("id")
                or riga.get("id_vettura")
                or riga.get("codice")
                or riga.get("deal_id")
                or ""
            )
            targa = riga.get("targa") or riga.get("licenseplate") or ""
            modello = estrai_modello_da_riga(riga)

            if not id_auto and not targa:
                continue

            chiave_id = id_auto if id_auto else targa

            opt1_val = (
                riga.get("stato_opzione1")
                or riga.get("stato_opzione_1")
                or riga.get("opzione1")
                or ""
            )
            opt2_val = (
                riga.get("stato_opzione2")
                or riga.get("stato_opzione_2")
                or riga.get("opzione2")
                or ""
            )
            url_foto = (
                riga.get("link2lifeimage")
                or riga.get("link_image")
                or riga.get("image_link")
                or ""
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

            vetture_attuali[chiave_id] = {
                "desc": " | ".join(desc_parti),
                "options": num_opzioni,
                "url_foto": url_foto,
            }

    print(f"Totale vetture lette dal CSV: {len(vetture_attuali)}")

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
