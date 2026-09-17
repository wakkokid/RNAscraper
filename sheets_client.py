"""
sheets_client.py - Modulo per l'integrazione con Google Sheets via gspread OAuth 2.0.

Responsabilità:
  - Autenticazione OAuth Desktop
  - Lettura del tab "Aziende" (lista CF/ragioni sociali)
  - Lettura stato corrente del tab "RNA"
  - Inizializzazione del tab "RNA" se assente
  - Scrittura batch degli aggiornamenti
"""

import logging
from typing import Optional
import gspread
from gspread import Spreadsheet, Worksheet

logger = logging.getLogger(__name__)

# ─── Costanti ───────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1HVyQUbdGMRCBnzCO8r3sFLeAEO6sZF7VglZuQ6u3c6U"

CREDENTIALS_FILE = (
    "PVT/client_secret_244769943975-b7i3r0hgpvhe3fcilsnua5r98cpe9mmb"
    ".apps.googleusercontent.com.json"
)
AUTHORIZED_USER_FILE = "PVT/authorized_user.json"

# Header atteso nel tab "RNA"
RNA_HEADERS = [
    "Azienda",
    "Codice Fiscale",
    "Totale Contributi",
    "Totale Ultimi 3 Anni",
    "Ultimo Contributo Ricevuto",
    "Data Ultimo Controllo",
    "Novità",
]

# ─── Funzioni pubbliche ──────────────────────────────────────────────────────


def get_client() -> gspread.Client:
    """Restituisce un client gspread autenticato via OAuth 2.0 Desktop."""
    logger.info("Autenticazione Google Sheets...")
    gc = gspread.oauth(
        credentials_filename=CREDENTIALS_FILE,
        authorized_user_filename=AUTHORIZED_USER_FILE,
    )
    logger.info("Autenticazione completata.")
    return gc


def open_spreadsheet(gc: gspread.Client) -> Spreadsheet:
    """Apre il foglio di lavoro per ID."""
    logger.info("Apertura spreadsheet %s", SPREADSHEET_ID)
    return gc.open_by_key(SPREADSHEET_ID)


def read_aziende(sh: Spreadsheet) -> list[dict]:
    """
    Legge il tab 'Aziende' e restituisce una lista di dict con chiavi:
      - 'ragione_sociale': str
      - 'codice_fiscale': str (trattato sempre come stringa, zero iniziali preservati)

    Salta la prima riga se è un'intestazione (contiene testo non numerico in col B).
    """
    ws: Worksheet = sh.worksheet("Aziende")
    all_rows = ws.get_all_values()

    if not all_rows:
        logger.warning("Tab 'Aziende' è vuoto!")
        return []

    # Determina se la prima riga è un header
    first_row = all_rows[0]
    col_b_first = first_row[1].strip() if len(first_row) > 1 else ""
    # Se la colonna B non è un CF valido (contiene lettere non fiscali → è header)
    is_header = not col_b_first.replace(" ", "").replace("-", "").isalnum() or len(col_b_first) < 5

    data_rows = all_rows[1:] if is_header else all_rows
    logger.info("Header rilevato: %s | Righe dati: %d", is_header, len(data_rows))

    aziende = []
    for i, row in enumerate(data_rows):
        if len(row) < 2:
            continue
        ragione = row[0].strip()
        cf = row[1].strip()  # Preserviamo come stringa
        if not cf:
            logger.warning("Riga %d: CF vuoto, salto.", i + 2)
            continue
        # Se è un CF numerico / Partita IVA (11 cifre) ma ha perso gli zeri iniziali in Sheets
        if cf.isdigit() and len(cf) < 11:
            cf_padded = cf.zfill(11)
            logger.info("Normalizzato CF numerico con zeri iniziali: %s -> %s", cf, cf_padded)
            cf = cf_padded
        aziende.append({"ragione_sociale": ragione, "codice_fiscale": cf})

    logger.info("Aziende lette: %d", len(aziende))
    return aziende


def read_rna_tab(sh: Spreadsheet, tab_name: str = "RNA") -> dict[str, dict]:
    """
    Legge il tab specificato (RNA o DeMinimis) e restituisce un dizionario con chiave = Codice Fiscale.
    Crea il tab se non esiste, inizializzandolo con le intestazioni corrette.

    Returns:
        dict { codice_fiscale -> { colonna: valore, ... } }
    """
    try:
        ws: Worksheet = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        logger.info("Tab '%s' non trovato. Creazione con intestazioni...", tab_name)
        ws = sh.add_worksheet(title=tab_name, rows=1000, cols=len(RNA_HEADERS))
        ws.append_row(RNA_HEADERS, value_input_option="USER_ENTERED")
        logger.info("Tab '%s' creato.", tab_name)
        return {}

    all_rows = ws.get_all_values()
    if not all_rows or all_rows[0][:len(RNA_HEADERS)] != RNA_HEADERS:
        # Tab esiste ma le intestazioni sono errate/assenti → le riscriviamo
        logger.warning("Tab '%s' senza header corretto. Inizializzazione...", tab_name)
        if not all_rows:
            ws.append_row(RNA_HEADERS, value_input_option="USER_ENTERED")
        else:
            ws.update("A1", [RNA_HEADERS], value_input_option="USER_ENTERED")
        return {}

    existing: dict[str, dict] = {}
    for row in all_rows[1:]:
        if len(row) < 2 or not row[1].strip():
            continue
        cf = row[1].strip().lstrip("'")
        if cf.isdigit() and len(cf) < 11:
            cf = cf.zfill(11)
        existing[cf] = {
            "azienda": row[0] if len(row) > 0 else "",
            "codice_fiscale": cf,
            "totale_contributi": row[2] if len(row) > 2 else "0",
            "totale_ultimi_3_anni": row[3] if len(row) > 3 else "0",
            "ultimo_contributo": row[4] if len(row) > 4 else "",
            "data_controllo": row[5] if len(row) > 5 else "",
            "novita": row[6] if len(row) > 6 else "",
        }

    logger.info("Righe %s esistenti caricate: %d", tab_name, len(existing))
    return existing


def get_rna_worksheet(sh: Spreadsheet, tab_name: str = "RNA") -> Worksheet:
    """Restituisce il worksheet richiesto (deve già esistere)."""
    return sh.worksheet(tab_name)


def batch_update_rna(ws: Worksheet, rows_to_update: list[list], tab_name: str = "RNA") -> None:
    """
    Sovrascrive l'intero contenuto del tab (eccetto l'header) con i nuovi dati.
    Usa update a blocchi per minimizzare le chiamate API.

    Args:
        ws: il Worksheet
        rows_to_update: lista di righe (list of list) da scrivere dalla riga 2 in poi
        tab_name: nome del tab (per logging)
    """
    if not rows_to_update:
        logger.info("Nessun dato da aggiornare su %s.", tab_name)
        return

    # Cancella tutto il contenuto dalla riga 2 in poi (mantiene header)
    # Poi scrive in blocco
    total_rows = len(rows_to_update)
    # Calcola range: A2:G{2+total-1}
    end_row = 1 + total_rows
    range_notation = f"A2:G{end_row}"

    logger.info("Batch update %s: %d righe → range %s", tab_name, total_rows, range_notation)
    ws.update(range_name=range_notation, values=rows_to_update, value_input_option="RAW")

    # Imposta formato valuta (Euro) con decimali per le colonne C (Totale Contributi) e D (Totale Ultimi 3 Anni)
    try:
        ws.format(f"C2:D{end_row}", {"numberFormat": {"type": "CURRENCY", "pattern": "#,##0.00 €"}})
        ws.format(f"B2:B{end_row}", {"numberFormat": {"type": "TEXT"}})
        logger.info("Formattazione valuta (#,##0.00 €) applicata su colonne C e D.")
    except Exception as e:
        logger.warning("Impossibile applicare formato valuta: %s", e)

    logger.info("Batch update completato su %s.", tab_name)

