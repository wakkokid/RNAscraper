"""
main.py - Entry point dello script RNAscraper.

Orchestrazione completa:
  1. Autenticazione Google Sheets
  2. Lettura lista aziende dal tab "Aziende"
  3. Lettura stato corrente del tab "RNA"
  4. Loop su ogni azienda: ricerca RNA + download + parsing
  5. Sincronizzazione batch sul tab "RNA"
  6. Log riepilogo finale

Uso:
    uv run python main.py
    oppure (con venv attivo):
    python main.py

Opzioni:
    --headless-off   : avvia il browser in modalità visibile (per debug)
    --dry-run        : non scrive su Google Sheets (solo log)
    --only-cf CF1,CF2: processa solo i CF specificati (comma-separated)
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from data_processor import RNAResult, cleanup_file, process_rna_file
from rna_scraper import rna_scraper_session
from sheets_client import (
    batch_update_rna,
    get_client,
    get_rna_worksheet,
    open_spreadsheet,
    read_aziende,
    read_rna_tab,
)
from sync_engine import build_rna_rows, summarize_changes

# ─── Logging Setup ───────────────────────────────────────────────────────────


def setup_logging(verbose: bool = False) -> None:
    """Configura il logging su console e file."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("rna_scraper.log", encoding="utf-8"),
    ]

    logging.basicConfig(level=level, format=log_format, datefmt=date_format, handlers=handlers)

    # Silenzia librerie verbose
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ─── Argomenti CLI ───────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RNAscraper - Automazione lettura aiuti RNA e sincronizzazione Google Sheets"
    )
    parser.add_argument(
        "--headless-off",
        action="store_true",
        default=False,
        help="Avvia il browser Chromium in modalità visibile (default: headless)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simula l'esecuzione senza scrivere su Google Sheets",
    )
    parser.add_argument(
        "--only-cf",
        type=str,
        default=None,
        help="Processa solo i Codici Fiscali indicati (comma-separated). Es: --only-cf CF1,CF2",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Logging verbose (DEBUG level)",
    )
    return parser.parse_args()


# ─── Logica principale ────────────────────────────────────────────────────────


def process_company(
    scraper,
    azienda: dict,
) -> Optional[RNAResult]:
    """
    Elabora una singola azienda:
      1. Ricerca RNA + download file (CSV/XLSX)
      2. Parsing e calcoli
      3. Conservazione del file scaricato nella cartella downloads/

    Restituisce RNAResult o None (nessun aiuto / errore).
    Non solleva eccezioni: le cattura e logga, per non bloccare il ciclo.
    """
    cf = azienda["codice_fiscale"]
    ragione = azienda["ragione_sociale"]
    logger.info("━━━ Elaborazione: %s (CF: %s) ━━━", ragione, cf)

    downloaded_path: Optional[Path] = None
    try:
        downloaded_path = scraper.search_and_download(cf)

        if downloaded_path is None:
            logger.info("  → Nessun aiuto registrato per %s", ragione)
            return None

        result = process_rna_file(downloaded_path)
        if result is None:
            logger.warning("  → File RNA vuoto o non processabile per %s", ragione)
            return None

        logger.info(
            "  → Totale: €%.2f | Ultimi 3 anni: €%.2f | Ultimo: %s",
            result.totale_contributi,
            result.totale_ultimi_3_anni,
            result.ultimo_contributo,
        )
        return result

    except Exception as e:
        logger.error("  → ERRORE per CF=%s (%s): %s", cf, ragione, e, exc_info=True)
        return None

    finally:
        if downloaded_path is not None:
            logger.info("  → File scaricato conservato in: %s", downloaded_path)


def run(args: argparse.Namespace) -> int:
    """
    Funzione principale di esecuzione.
    Restituisce exit code: 0 = successo, 1 = errore critico.
    """
    logger.info("═══════════════════════════════════════════")
    logger.info("  RNAscraper avviato")
    logger.info("  Dry-run: %s | Headless: %s", args.dry_run, not args.headless_off)
    logger.info("═══════════════════════════════════════════")

    # ── 1. Autenticazione e lettura Google Sheets ──────────────────────────
    try:
        gc = get_client()
        sh = open_spreadsheet(gc)
        logger.info("Spreadsheet aperto con successo.")
    except Exception as e:
        logger.critical("Errore connessione Google Sheets: %s", e, exc_info=True)
        return 1

    # ── 2. Lettura lista aziende ───────────────────────────────────────────
    try:
        aziende = read_aziende(sh)
    except Exception as e:
        logger.critical("Errore lettura tab 'Aziende': %s", e, exc_info=True)
        return 1

    if not aziende:
        logger.warning("Nessuna azienda trovata nel tab 'Aziende'. Uscita.")
        return 0

    # ── Filtro --only-cf ───────────────────────────────────────────────────
    if args.only_cf:
        filter_cfs = {cf.strip() for cf in args.only_cf.split(",")}
        aziende = [a for a in aziende if a["codice_fiscale"] in filter_cfs]
        logger.info("Filtro --only-cf applicato: %d aziende selezionate", len(aziende))

    # ── 3. Lettura stato corrente tab RNA ──────────────────────────────────
    try:
        existing_rna = read_rna_tab(sh)
    except Exception as e:
        logger.error("Errore lettura tab 'RNA': %s. Procedo con stato vuoto.", e)
        existing_rna = {}

    # ── 4. Loop principale: scraping RNA ───────────────────────────────────
    results: dict[str, Optional[RNAResult]] = {}
    headless = not args.headless_off

    # Cartella download fissa e visibile (invece di tempfile casuale)
    download_dir = Path(__file__).parent / "downloads"
    download_dir.mkdir(exist_ok=True)
    logger.info("File RNA scaricati in: %s", download_dir)

    with rna_scraper_session(headless=headless, download_dir=str(download_dir)) as scraper:
        for i, azienda in enumerate(aziende):
            cf = azienda["codice_fiscale"]
            logger.info("[%d/%d] Elaborazione %s...", i + 1, len(aziende), cf)
            result = process_company(scraper, azienda)
            results[cf] = result

    # ── 5. Costruzione righe aggiornate ────────────────────────────────────
    output_rows = build_rna_rows(aziende, results, existing_rna)
    stats = summarize_changes(output_rows)

    logger.info("─── Riepilogo modifiche ───")
    logger.info("  Totale aziende:    %d", stats["totale"])
    logger.info("  Nuovi inserimenti: %d", stats["nuovi"])
    logger.info("  Totali aggiornati: %d", stats["aggiornati"])
    logger.info("  Invariati:         %d", stats["invariati"])

    # ── 6. Scrittura su Google Sheets ─────────────────────────────────────
    if args.dry_run:
        logger.info("DRY-RUN: Nessuna scrittura su Google Sheets.")
        logger.info("Righe che sarebbero state scritte:")
        for row in output_rows:
            logger.info("  %s", row)
    else:
        try:
            ws_rna = get_rna_worksheet(sh)
            batch_update_rna(ws_rna, output_rows)
            logger.info("Tab 'RNA' aggiornato con successo!")
        except Exception as e:
            logger.error("Errore scrittura tab 'RNA': %s", e, exc_info=True)
            return 1

    logger.info("═══════════════════════════════════════════")
    logger.info("  RNAscraper completato con successo.")
    logger.info("═══════════════════════════════════════════")
    return 0


# ─── Entry Point ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    args = parse_args()
    setup_logging(verbose=args.verbose)
    sys.exit(run(args))

