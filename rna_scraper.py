"""
rna_scraper.py - Automazione Playwright per il portale RNA.

Responsabilità:
  - Gestione sessione browser Chromium (headless)
  - Accettazione banner cookie (una sola volta per sessione)
  - Ricerca per Codice Fiscale/P.IVA
  - Rilevamento assenza risultati
  - Download file XLSX degli aiuti in cartella temporanea
  - Pulizia file temporanei dopo elaborazione

Selettori identificati con ispezione DOM (inspect_rna.py):
  - Cookie accept:  button:has-text('Accetta')
  - CF input:       #cfBen
  - Search button:  #reloadTable
  - Export XLSX:    a.exportbox_link[data-type="xlsx"]
  - Table:          #trasparenzaAiuti
  - Empty message:  "Nessun dato disponibile nella tabella"
  - Download box:   #DownloadsBox
"""

import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)

RNA_URL = "https://www.rna.gov.it/trasparenza/aiuti"

# Timeout in ms
NAV_TIMEOUT = 60_000
SEARCH_TIMEOUT = 30_000
DOWNLOAD_TIMEOUT = 60_000
ELEMENT_TIMEOUT = 10_000


class RNAScraper:
    """
    Classe che gestisce l'intera sessione di scraping sul portale RNA.
    Mantiene un singolo browser/context tra più ricerche per efficienza.
    """

    def __init__(self, headless: bool = True, download_dir: Optional[str] = None):
        self.headless = headless
        self.download_dir = download_dir or tempfile.mkdtemp(prefix="rna_downloads_")
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cookie_accepted: bool = False

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Avvia il browser Chromium e naviga sulla pagina RNA."""
        logger.info("Avvio browser Chromium (headless=%s)...", self.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(accept_downloads=True)
        self._page = self._context.new_page()

        logger.info("Navigazione su %s ...", RNA_URL)
        self._page.goto(RNA_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        self._accept_cookies()

    def stop(self) -> None:
        """Chiude browser e Playwright."""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning("Errore nella chiusura del browser: %s", e)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    # ─── Cookie ─────────────────────────────────────────────────────────────

    def _accept_cookies(self) -> None:
        """
        Accetta il banner cookie del sito RNA e naviga al form di ricerca.

        Il sito RNA, dopo il click su 'Accetta', rimane sulla pagina
        'Consenso ai cookie' (errore-cookies) e NON carica automaticamente
        la pagina con il form. Bisogna:
          1. Cliccare Accetta
          2. Rinavigare esplicitamente a RNA_URL
          3. Attendere che il campo #cfBen sia visibile e interattivo
        """
        if self._cookie_accepted:
            return
        page = self._page
        assert page is not None

        cookie_selectors = [
            "button:has-text('Accetta')",
            "button:has-text('ACCETTA I COOKIE')",
            "#cookieAccept",
            "button.cookiebar-btn-accept",
            # Pulsante nel banner in basso (cookiebar)
            "button[id*='cookie']:has-text('Accetta')",
        ]

        clicked = False
        for sel in cookie_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    logger.info("Banner cookie trovato (%s). Click...", sel)
                    btn.click()
                    page.wait_for_timeout(1000)
                    clicked = True
                    logger.info("Cookie accettati.")
                    break
            except PlaywrightTimeoutError:
                pass
            except Exception as e:
                logger.debug("Selettore cookie %r fallito: %s", sel, e)

        if not clicked:
            logger.info("Nessun banner cookie trovato (già accettato o assente).")

        # ── Rinaviga esplicitamente al form RNA ────────────────────────────
        # Il sito dopo l'accept rimane su /trasparenza/errore-cookies
        # oppure la sessione con cookie non è ancora propagata.
        # Facciamo un goto forzato + wait per domcontentloaded.
        logger.info("Rinavigazione verso %s per caricare il form...", RNA_URL)
        page.goto(RNA_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # ── Attendi che il campo CF sia visibile e interattivo ─────────────
        try:
            page.locator("#cfBen").wait_for(state="visible", timeout=15_000)
            logger.info("Form RNA caricato correttamente (#cfBen visibile).")
        except PlaywrightTimeoutError:
            logger.warning(
                "#cfBen non visibile dopo 15s. Il form potrebbe non essere caricato. "
                "Provo un secondo reload..."
            )
            page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(3000)
            try:
                page.locator("#cfBen").wait_for(state="visible", timeout=15_000)
                logger.info("Form RNA caricato al secondo tentativo.")
            except PlaywrightTimeoutError:
                logger.error(
                    "Impossibile caricare il form RNA dopo 2 tentativi! "
                    "URL corrente: %s", page.url
                )

        self._cookie_accepted = True

    # ─── Ricerca e Download ──────────────────────────────────────────────────

    def search_and_download(self, codice_fiscale: str) -> Optional[Path]:
        """
        Esegue la ricerca per un Codice Fiscale/P.IVA sul portale RNA.

        Returns:
            Path del file XLSX scaricato, oppure None se nessun risultato trovato.

        Raises:
            Exception in caso di errori di navigazione non recuperabili.
        """
        page = self._page
        assert page is not None

        cf = codice_fiscale.strip()
        logger.info("Ricerca RNA per CF: %s", cf)

        # ── 1. Reset del form: pulisci il campo CF e reinserisci ──────────────
        try:
            cf_input = page.locator("#cfBen")
            cf_input.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
            # fill() svuota automaticamente il campo prima di scrivere
            cf_input.fill(cf)
            logger.debug("CF inserito: %r", cf)
        except PlaywrightTimeoutError:
            logger.error("Input #cfBen non trovato entro %dms!", ELEMENT_TIMEOUT)
            raise

        # ── 2. Snapshot info bar PRIMA del click ─────────────────────────────
        # Leggiamo il testo attuale dell'info bar per sapere quando cambia
        info_before = ""
        try:
            info_el = page.locator("#trasparenzaAiuti_info")
            if info_el.count() > 0:
                info_before = info_el.first.inner_text(timeout=3000).strip()
                logger.debug("Info bar PRIMA click: %r", info_before)
        except Exception:
            pass

        # ── 3. Click su "AVVIA RICERCA" ──────────────────────────────────────
        try:
            search_btn = page.locator("#reloadTable")
            search_btn.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
            search_btn.click()
            logger.debug("Pulsante ricerca cliccato.")
        except PlaywrightTimeoutError:
            logger.error("Pulsante #reloadTable non trovato!")
            raise

        # ── 4. Attendi che la DataTable finisca di caricare ───────────────────
        # Strategia robusta in 2 fasi:
        #   A) Aspetta che il div #trasparenzaAiuti_processing appaia (AJAX iniziato)
        #   B) Aspetta che scompaia (AJAX terminato)
        # Se la fase A non avviene (processing mai visibile), usiamo un fallback
        # che aspetta che l'info bar cambi rispetto allo snapshot precedente.
        AJAX_APPEAR_TIMEOUT = 5_000   # ms per vedere il processing spinner
        AJAX_DONE_TIMEOUT   = 30_000  # ms per aspettare fine AJAX

        processing_appeared = False
        try:
            # Fase A: aspetta che processing appaia
            page.locator("#trasparenzaAiuti_processing").wait_for(
                state="visible", timeout=AJAX_APPEAR_TIMEOUT
            )
            processing_appeared = True
            logger.debug("Spinner processing apparso → AJAX in corso...")
        except PlaywrightTimeoutError:
            logger.debug("Spinner processing non apparso (AJAX molto veloce o assente).")

        if processing_appeared:
            # Fase B: aspetta che processing scompaia
            try:
                page.locator("#trasparenzaAiuti_processing").wait_for(
                    state="hidden", timeout=AJAX_DONE_TIMEOUT
                )
                logger.debug("Spinner processing scomparso → AJAX completato.")
            except PlaywrightTimeoutError:
                logger.warning("Timeout attesa fine AJAX (CF=%s). Provo a continuare...", cf)
        else:
            # Fallback: aspetta che l'info bar cambi rispetto allo snapshot
            # (significa che la DataTable ha ricevuto risposta dal server)
            info_before_escaped = info_before.replace("'", "\\'")
            try:
                page.wait_for_function(
                    f"""() => {{
                        const el = document.querySelector('#trasparenzaAiuti_info');
                        if (!el) return false;
                        const current = el.innerText.trim();
                        // L'info bar è cambiata rispetto allo stato pre-click
                        return current !== '{info_before_escaped}';
                    }}""",
                    timeout=AJAX_DONE_TIMEOUT,
                )
                logger.debug("Info bar cambiata → AJAX completato (fallback).")
            except PlaywrightTimeoutError:
                logger.warning(
                    "Info bar invariata dopo %dms (CF=%s). "
                    "Possibile risultato vuoto o timeout.", AJAX_DONE_TIMEOUT, cf
                )

        # Piccola pausa finale per stabilizzazione DOM
        page.wait_for_timeout(500)

        # ── 5. Verifica se ci sono risultati ──────────────────────────────────
        if self._has_no_results():
            logger.info("Nessun aiuto registrato per CF=%s", cf)
            self._reset_search()
            return None

        # ── 6. Download XLSX ──────────────────────────────────────────────────
        downloaded_path = self._download_xlsx(cf)
        self._reset_search()
        return downloaded_path

    def _has_no_results(self) -> bool:
        """
        Verifica se la tabella risultati è vuota.

        Strategia (in ordine di affidabilità):
          1. Info bar DataTable: "Risultati da 0 a 0 di 0 elementi" → nessun risultato
          2. Cella .dataTables_empty nel tbody → nessun risultato
          3. Conteggio righe tbody = 0 → nessun risultato
        """
        page = self._page
        assert page is not None

        # ── Controllo 1: info bar DataTable (più affidabile) ──────────────────
        # L'info bar mostra "Risultati da 0 a 0 di 0 elementi" quando non ci sono dati
        try:
            info_el = page.locator("#trasparenzaAiuti_info")
            if info_el.count() > 0:
                info_text = info_el.first.inner_text(timeout=3000)
                # Cerca "di 0 elementi" nell'info bar
                if "di 0 elementi" in info_text or "of 0 entries" in info_text.lower():
                    logger.debug("Info bar conferma: 0 elementi trovati (%r)", info_text.strip())
                    return True
        except Exception as e:
            logger.debug("Controllo info bar fallito: %s", e)

        # ── Controllo 2: cella .dataTables_empty nel tbody ─────────────────────
        empty_sel = "#trasparenzaAiuti tbody .dataTables_empty"
        try:
            empty_cell = page.locator(empty_sel)
            if empty_cell.count() > 0 and empty_cell.first.is_visible(timeout=2000):
                text = empty_cell.first.inner_text()
                if "Nessun dato" in text or "No data" in text.lower():
                    return True
        except Exception:
            pass

        # ── Controllo 3: fallback conteggio righe ─────────────────────────────
        try:
            row_count = page.locator("#trasparenzaAiuti tbody tr").count()
            if row_count == 0:
                return True
            if row_count == 1:
                single_row_text = page.locator(
                    "#trasparenzaAiuti tbody tr"
                ).first.inner_text()
                if "Nessun dato" in single_row_text or single_row_text.strip() == "":
                    return True
        except Exception as e:
            logger.debug("Errore conteggio righe tabella: %s", e)

        return False

    def _download_xlsx(self, cf: str) -> Optional[Path]:
        """
        Clicca sul pulsante 'Scarica XLSX' e intercetta il download.
        Restituisce il Path del file scaricato o None in caso di errore.
        """
        page = self._page
        assert page is not None

        # Potrebbe essere necessario rendere visibile il DownloadsBox
        # Il sito lo mostra solo dopo che ci sono risultati
        xlsx_selector = "a.exportbox_link[data-type='xlsx']"
        csv_selector = "a.exportbox_link[data-type='csv']"

        # Prova prima CSV (preferito dall'utente), fallback su XLSX
        for selector, ext in [(csv_selector, "csv"), (xlsx_selector, "xlsx")]:
            try:
                btn = page.locator(selector)
                if btn.count() == 0:
                    continue

                logger.info("Tentativo download %s per CF=%s ...", ext.upper(), cf)

                with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                    btn.first.click()

                download = download_info.value
                filename = f"rna_{cf}.{ext}"
                dest_path = Path(self.download_dir) / filename

                download.save_as(str(dest_path))
                logger.info("File scaricato: %s", dest_path)
                return dest_path

            except PlaywrightTimeoutError:
                logger.warning("Timeout download %s per CF=%s", ext.upper(), cf)
            except Exception as e:
                logger.warning("Errore download %s per CF=%s: %s", ext.upper(), cf, e)

        logger.error("Impossibile scaricare file per CF=%s", cf)
        return None

    def _reset_search(self) -> None:
        """Pulisce il campo CF per preparare la prossima ricerca."""
        page = self._page
        assert page is not None
        try:
            cf_input = page.locator("#cfBen")
            cf_input.fill("")  # fill("") svuota il campo
        except Exception as e:
            logger.debug("Errore reset campo CF: %s", e)


@contextmanager
def rna_scraper_session(
    headless: bool = True, download_dir: Optional[str] = None
) -> Generator[RNAScraper, None, None]:
    """
    Context manager per gestire il lifecycle completo del scraper RNA.

    Uso:
        with rna_scraper_session(download_dir="downloads") as scraper:
            path = scraper.search_and_download("RSSMRA80A01H501U")
    """
    scraper = RNAScraper(headless=headless, download_dir=download_dir)
    try:
        scraper.start()
        yield scraper
    finally:
        scraper.stop()

