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
import signal
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

abort_requested = False

def handle_signal(signum, frame):
    global abort_requested
    if not abort_requested:
        abort_requested = True
        logger = logging.getLogger(__name__)
        logger.warning("\n[!] Ricevuto segnale di stop (Ctrl+C o kill). Il bot si fermerà in modo pulito alla fine dell'azienda corrente...")

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
        "--limit",
        type=int,
        default=None,
        help="Limita l'esecuzione alle prime N aziende (utile per test)",
    )
    parser.add_argument(
        "--resend-email",
        action="store_true",
        default=False,
        help="Ritenta l'invio dell'ultima email usando i dati salvati, senza eseguire lo scraping",
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
    tipo_procedimento: Optional[str] = None,
    progress_perc: str = ""
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
    label_proc = tipo_procedimento or "Generale"
    prefix = f" {progress_perc}" if progress_perc else ""
    logger.info("━━━%s Elaborazione %s: %s (CF: %s) ━━━", prefix, label_proc.upper(), ragione, cf)

    downloaded_path: Optional[Path] = None
    try:
        downloaded_path = scraper.search_and_download(cf, tipo_procedimento=tipo_procedimento)

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
    global abort_requested
    abort_requested = False
    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except Exception as e:
        logger.debug("Impossibile registrare gli handler di segnale: %s", e)

    if args.resend_email:
        logger.info("=== Modalità RE-INVIO EMAIL ===")
        try:
            from mailer import load_email_data, send_notification
            data = load_email_data()
            if data is not None:
                # send_notification si occuperà di salvare e inviare (sovrascrivendo lo stesso json, va bene)
                send_notification(data)
            else:
                logger.error("Dati email non disponibili per il reinvio.")
        except Exception as e:
            logger.error("Errore nel reinvio email: %s", e)
        return 0

    logger.info("═══════════════════════════════════════════")
    logger.info("  RNAscraper avviato")
    logger.info("  Dry-run: %s | Headless: %s", args.dry_run, not args.headless_off)
    logger.info("═══════════════════════════════════════════")

    # ─── 2. Autenticazione e Lettura Input ───────────────────────────────────
    try:
        logger.info("Autenticazione Google Sheets...")
        gc = get_client()
        logger.info("Autenticazione completata.")
        
        if abort_requested:
            logger.warning("Interruzione durante l'avvio. Chiusura script.")
            return 0
            
        sh = open_spreadsheet(gc)
        logger.info("Spreadsheet aperto con successo.")
        
        if abort_requested:
            logger.warning("Interruzione durante l'avvio. Chiusura script.")
            return 0

        aziende = read_aziende(sh)
    except Exception as e:
        logger.critical("Errore connessione Google Sheets: %s", e, exc_info=True)
        return 1

    if not aziende:
        logger.warning("Nessuna azienda trovata nel tab 'Aziende'. Uscita.")
        return 0

    # ── Filtro --only-cf ───────────────────────────────────────────────────
    if args.only_cf:
        filter_cfs = {cf.strip() for cf in args.only_cf.split(",")}
        aziende = [a for a in aziende if a["codice_fiscale"] in filter_cfs]
        logger.info("Filtro --only-cf applicato: %d aziende selezionate", len(aziende))

    # ── Filtro --limit ─────────────────────────────────────────────────────
    if args.limit and args.limit > 0:
        aziende = aziende[:args.limit]
        logger.info("Filtro --limit applicato: %d aziende selezionate", len(aziende))

    # ── 3. Lettura stato corrente tab RNA e DeMinimis ───────────────────────
    try:
        existing_rna = read_rna_tab(sh, tab_name="RNA")
    except Exception as e:
        logger.error("Errore lettura tab 'RNA': %s. Procedo con stato vuoto.", e)
        existing_rna = {}
        
    try:
        existing_deminimis = read_rna_tab(sh, tab_name="DeMinimis")
    except Exception as e:
        logger.error("Errore lettura tab 'DeMinimis': %s. Procedo con stato vuoto.", e)
        existing_deminimis = {}

    # ── 4. Loop principale: scraping RNA ───────────────────────────────────
    results_rna: dict[str, Optional[RNAResult]] = {}
    results_deminimis: dict[str, Optional[RNAResult]] = {}
    scraped_cfs: set[str] = set()
    headless = not args.headless_off

    # Cartella download fissa e visibile (invece di tempfile casuale)
    download_dir = Path(__file__).parent / "downloads"
    download_dir.mkdir(exist_ok=True)
    logger.info("File RNA scaricati in: %s", download_dir)

    def do_batch_save():
        if args.dry_run:
            logger.info("DRY-RUN: Skip salvataggio batch su Google Sheets.")
            return
        logger.info("Salvataggio batch intermedio su Google Sheets...")
        out_rna = build_rna_rows(aziende, results_rna, existing_rna, scraped_cfs)
        out_deminimis = build_rna_rows(aziende, results_deminimis, existing_deminimis, scraped_cfs)
        try:
            ws_rna = get_rna_worksheet(sh, tab_name="RNA")
            batch_update_rna(ws_rna, out_rna, tab_name="RNA")
        except Exception as e:
            logger.error("Errore scrittura batch tab 'RNA': %s", e)
            
        try:
            ws_deminimis = get_rna_worksheet(sh, tab_name="DeMinimis")
            batch_update_rna(ws_deminimis, out_deminimis, tab_name="DeMinimis")
        except Exception as e:
            logger.error("Errore scrittura batch tab 'DeMinimis': %s", e)

    from sync_engine import _amounts_differ, _parse_amount_str
    from data_processor import RNAResult
    excel_downloads_count = 0

    with rna_scraper_session(headless=headless, download_dir=str(download_dir)) as scraper:
        for i, azienda in enumerate(aziende):
            if abort_requested:
                logger.warning("Interruzione confermata. Uscita anticipata dal ciclo di scraping...")
                break
                
            cf = azienda["codice_fiscale"]
            perc_str = f"{int((i / len(aziende)) * 100)}%"
            logger.info("[%d/%d] Elaborazione %s...", i + 1, len(aziende), cf)
            
            if cf in scraped_cfs:
                logger.info("  -> CF %s già elaborato in precedenza (doppione). Salto lo scraping per %s.", cf, azienda.get("ragione_sociale", ""))
                continue
            
            needs_deminimis = False

            # 1. Ricerca Generale RNA
            res_rna = process_company(scraper, azienda, tipo_procedimento=None, progress_perc=perc_str)
            results_rna[cf] = res_rna
            if res_rna:
                old = existing_rna.get(cf, {})
                t_chg = _amounts_differ(old.get("totale_contributi", "0"), res_rna.totale_contributi)
                u_chg = _amounts_differ(old.get("totale_ultimi_3_anni", "0"), res_rna.totale_ultimi_3_anni)
                is_new = cf not in existing_rna
                
                if is_new or t_chg or u_chg:
                    needs_deminimis = True
                    if excel_downloads_count < 25 and (t_chg or u_chg or res_rna.totale_contributi > 0):
                        scraper.download_excel(cf, prefix="rna")
                        excel_downloads_count += 1
            else:
                # Se non trova RNA, controlla se prima c'era (diventato 0)
                if cf in existing_rna and _parse_amount_str(existing_rna[cf].get("totale_contributi", "0")) > 0:
                    needs_deminimis = True
            
            # Se la memoria di DeMinimis per l'azienda è vuota, dobbiamo cercarla comunque
            if cf not in existing_deminimis:
                needs_deminimis = True

            # 2. Ricerca De Minimis
            if needs_deminimis:
                res_deminimis = process_company(scraper, azienda, tipo_procedimento="De Minimis", progress_perc=perc_str)
                results_deminimis[cf] = res_deminimis
                if res_deminimis and excel_downloads_count < 25:
                    old_dem = existing_deminimis.get(cf, {})
                    t_chg = _amounts_differ(old_dem.get("totale_contributi", "0"), res_deminimis.totale_contributi)
                    u_chg = _amounts_differ(old_dem.get("totale_ultimi_3_anni", "0"), res_deminimis.totale_ultimi_3_anni)
                    if (cf not in existing_deminimis and res_deminimis.totale_contributi > 0) or t_chg or u_chg:
                        scraper.download_excel(cf, prefix="deminimis")
                        excel_downloads_count += 1
            else:
                logger.info("  -> RNA immutato o vuoto. Salto ricerca De Minimis per ottimizzare.")
                old_dem = existing_deminimis.get(cf, {})
                if old_dem:
                    results_deminimis[cf] = RNAResult(
                        totale_contributi=_parse_amount_str(old_dem.get("totale_contributi", "0")),
                        totale_ultimi_3_anni=_parse_amount_str(old_dem.get("totale_ultimi_3_anni", "0")),
                        ultimo_contributo=old_dem.get("ultimo_contributo", "N/D")
                    )
                else:
                    results_deminimis[cf] = None

            scraped_cfs.add(cf)

            # Salva ogni 10 aziende
            if (i + 1) % 10 == 0:
                do_batch_save()
                
            # Attesa umana (macro-delay) tra un'azienda e l'altra, se non è l'ultima
            if i < len(aziende) - 1 and not abort_requested:
                from delay_manager import wait_macro
                wait_macro(scraper._page)

    # Salvataggio batch finale per quelle rimanenti (o in caso di abort)
    if len(scraped_cfs) > 0 and (len(scraped_cfs) % 10 != 0 or abort_requested):
        do_batch_save()

    # ─── 5. Costruzione righe aggiornate per statistiche finali ──────────────
    output_rows_rna = build_rna_rows(aziende, results_rna, existing_rna, scraped_cfs)
    output_rows_deminimis = build_rna_rows(aziende, results_deminimis, existing_deminimis, scraped_cfs)
    
    stats_rna = summarize_changes(output_rows_rna)
    stats_deminimis = summarize_changes(output_rows_deminimis)

    logger.info("─── Riepilogo modifiche RNA ───")
    logger.info("  Totale aziende:    %d", stats_rna["totale"])
    logger.info("  Nuovi inserimenti: %d", stats_rna["nuovi"])
    logger.info("  Totali aggiornati: %d", stats_rna["aggiornati"])
    logger.info("  Invariati:         %d", stats_rna["invariati"])
    
    logger.info("─── Riepilogo modifiche DeMinimis ───")
    logger.info("  Totale aziende:    %d", stats_deminimis["totale"])
    logger.info("  Nuovi inserimenti: %d", stats_deminimis["nuovi"])
    logger.info("  Totali aggiornati: %d", stats_deminimis["aggiornati"])
    logger.info("  Invariati:         %d", stats_deminimis["invariati"])

    # ── 6. Invio Email di Notifica e Log Storico ──────────────────────────────
    updates_to_send = []
    if stats_rna.get("dettagli_aggiornati"):
        updates_to_send.append(("Generale (RNA)", stats_rna["dettagli_aggiornati"]))
    if stats_deminimis.get("dettagli_aggiornati"):
        updates_to_send.append(("De Minimis", stats_deminimis["dettagli_aggiornati"]))

    if args.dry_run:
        logger.info("DRY-RUN: Skip invio email di notifica e scrittura Log storico.")
    else:
        # Costruisci righe per tab Log
        if updates_to_send:
            try:
                from datetime import datetime
                from sheets_client import append_to_log_tab
                
                timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                log_rows = []
                for category, companies in updates_to_send:
                    for comp in companies:
                        log_rows.append([
                            timestamp,
                            category,
                            comp.get("ragione", ""),
                            comp.get("cf", ""),
                            round(float(comp.get("variazione", 0.0)), 2),
                            round(float(comp.get("ultimi_3a", 0.0)), 2),
                            comp.get("ultimo_contributo", "")
                        ])
                append_to_log_tab(sh, log_rows)
            except Exception as e:
                logger.error("Impossibile salvare il log storico su Google Sheets: %s", e)
                
        # Invia email
        try:
            from mailer import send_notification
            send_notification(updates_to_send)
        except Exception as e:
            logger.error("Impossibile inviare l'email di notifica: %s", e)

    logger.info("═══════════════════════════════════════════")
    logger.info("  RNAscraper completato con successo.")
    logger.info("═══════════════════════════════════════════")
    return 0


# ─── Entry Point ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    args = parse_args()
    setup_logging(verbose=args.verbose)
    sys.exit(run(args))

