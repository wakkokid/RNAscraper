"""
Script di ispezione del portale RNA per identificare i selettori DOM.
Da eseguire una sola volta per debug/ispezione. Non fa parte del prodotto finale.
"""
from playwright.sync_api import sync_playwright
import json

def inspect_rna():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context()
        page = context.new_page()

        print("[*] Navigazione su RNA...")
        page.goto("https://www.rna.gov.it/trasparenza/aiuti", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        print(f"    URL dopo primo goto: {page.url}")

        print("[*] Cerco pulsante accetta cookie...")
        cookie_selectors = [
            "button:has-text('Accetta')",
            "button:has-text('ACCETTA I COOKIE')",
            "button:has-text('Accetta cookies')",
        ]
        clicked = False
        for sel in cookie_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    print(f"  -> Cookie button trovato: {sel}")
                    btn.click()
                    page.wait_for_timeout(1000)
                    clicked = True
                    break
            except Exception:
                pass

        print(f"    URL dopo cookie click: {page.url}")

        # ── NUOVO: rinavigazione forzata al form ──────────────────────────
        print("[*] Rinavigazione forzata verso il form RNA...")
        page.goto("https://www.rna.gov.it/trasparenza/aiuti", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        print(f"    URL dopo rinavigazione: {page.url}")

        # ── Attendi #cfBen ────────────────────────────────────────────────
        print("[*] Attendo visibilità #cfBen...")
        try:
            page.locator("#cfBen").wait_for(state="visible", timeout=15000)
            print("  -> #cfBen VISIBILE! Form caricato correttamente.")
        except Exception as e:
            print(f"  -> #cfBen NON visibile: {e}")
            print("     Provo reload...")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            try:
                page.locator("#cfBen").wait_for(state="visible", timeout=10000)
                print("  -> #cfBen visibile dopo reload.")
            except Exception as e2:
                print(f"  -> Ancora non visibile: {e2}")

        # ── Test inserimento CF ───────────────────────────────────────────
        cf_test = "00856180153"  # CF di test (Pirelli S.p.A.)
        print(f"\n[*] Test inserimento CF: {cf_test}")
        try:
            cf_input = page.locator("#cfBen")
            cf_input.fill(cf_test)
            print("  -> CF inserito")

            search_btn = page.locator("#reloadTable")
            search_btn.click()
            print("  -> Ricerca avviata")

            page.wait_for_timeout(5000)

            # Verifica risultati
            rows = page.locator("#trasparenzaAiuti tbody tr").count()
            print(f"  -> Righe risultato: {rows}")

            # Info tabella
            try:
                info_text = page.locator("#trasparenzaAiuti_info").inner_text()
                print(f"  -> Info tabella: {info_text}")
            except Exception:
                pass

        except Exception as e:
            print(f"  -> Errore test CF: {e}")

        # Salva HTML dopo ricerca
        html = page.content()
        with open("rna_page_after_search.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\n[*] HTML post-ricerca salvato in rna_page_after_search.html")

        page.wait_for_timeout(5000)
        browser.close()

if __name__ == "__main__":
    inspect_rna()

