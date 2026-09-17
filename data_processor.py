"""
data_processor.py - Parsing e calcoli pandas sui file scaricati dal portale RNA.

Responsabilità:
  - Lettura file XLSX o CSV scaricati da RNA
  - Normalizzazione colonne importo (separatori italiani: . migliaia, , decimali)
  - Normalizzazione date
  - Calcolo Totale Complessivo
  - Calcolo Totale Ultimi 3 Anni (1095 giorni)
  - Identificazione Ultimo Contributo (misura più recente)
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Numero di giorni per "ultimi 3 anni"
DAYS_3_YEARS = 1095

# Colonne possibili per l'importo dell'aiuto (in ordine di priorità)
AMOUNT_COLS_CANDIDATES = [
    "Elemento Aiuto",
    "Elemento aiuto",
    "Elemento di aiuto",
    "Importo nominale",
    "Importo Nominale",
    "Importo agevolazione",
    "Importo Agevolazione",
    "Importo",
    "Contributo",
    "Valore",
]

# Colonne possibili per la data di concessione
DATE_COLS_CANDIDATES = [
    "Data concessione",
    "Data Concessione",
    "data_concessione",
    "Data",
    "Anno concessione",
    "Anno Concessione",
]

# Colonne possibili per il titolo/nome della misura
TITLE_COLS_CANDIDATES = [
    "Titolo misura",
    "Titolo Misura",
    "Denominazione misura",
    "Denominazione Misura",
    "Titolo progetto",
    "Titolo Progetto",
    "Denominazione progetto",
    "Denominazione Progetto",
    "Misura",
    "Descrizione",
]


# ─── Dataclass risultato ─────────────────────────────────────────────────────


class RNAResult:
    """Risultato dell'elaborazione dei dati RNA per un'azienda."""

    def __init__(
        self,
        totale_contributi: float,
        totale_ultimi_3_anni: float,
        ultimo_contributo: str,
    ):
        self.totale_contributi = totale_contributi
        self.totale_ultimi_3_anni = totale_ultimi_3_anni
        self.ultimo_contributo = ultimo_contributo

    def __repr__(self) -> str:
        return (
            f"RNAResult(totale={self.totale_contributi:.2f}, "
            f"ultimi_3a={self.totale_ultimi_3_anni:.2f}, "
            f"ultimo={self.ultimo_contributo!r})"
        )


# ─── Funzioni private ────────────────────────────────────────────────────────


def _normalize_amount(value: str) -> float:
    """
    Converte un importo in formato italiano (es. '1.234.567,89') in float.
    Gestisce anche valori senza decimali, con simbolo €, ecc.
    Restituisce 0.0 in caso di valore non parsabile.
    """
    if pd.isna(value) or str(value).strip() == "":
        return 0.0
    s = str(value).strip()
    # Rimuovi simbolo € e spazi
    s = s.replace("€", "").replace(" ", "").replace("\xa0", "")
    # Formato italiano: punto = migliaia, virgola = decimale
    # Conta virgole e punti per capire il formato
    n_dot = s.count(".")
    n_comma = s.count(",")

    if n_comma == 1 and n_dot >= 1:
        # Es. '1.234.567,89' → rimuovi punti, sostituisci virgola con punto
        s = s.replace(".", "").replace(",", ".")
    elif n_comma == 1 and n_dot == 0:
        # Es. '1234,89' → solo decimale con virgola
        s = s.replace(",", ".")
    elif n_dot == 1 and n_comma == 0:
        # Es. '1234.56' → già formato anglosassone, oppure migliaia senza decimale
        pass  # lasciamo così
    elif n_comma == 0 and n_dot > 1:
        # Es. '1.234.567' → solo migliaia italiane
        s = s.replace(".", "")
    # Altro: proviamo a parsare così com'è

    try:
        return float(s)
    except ValueError:
        logger.debug("Impossibile parsare importo: %r → 0.0", value)
        return 0.0


def _parse_date(value: str) -> Optional[datetime]:
    """
    Prova a parsare una data in vari formati italiani/internazionali.
    Restituisce None se non parsabile.
    """
    if pd.isna(value) or str(value).strip() == "":
        return None
    s = str(value).strip()

    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%y",
        "%Y",       # solo anno (es. "2023")
        "%m/%Y",    # mese/anno
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # Prova pandas (più flessibile)
    try:
        return pd.to_datetime(s, dayfirst=True).to_pydatetime()
    except Exception:
        pass

    logger.debug("Data non parsabile: %r", value)
    return None


def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """
    Cerca tra le colonne del DataFrame la prima che corrisponde a una
    delle candidate (case-insensitive, rimuovendo spazi extra).
    """
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        if candidate.lower().strip() in cols_lower:
            return cols_lower[candidate.lower().strip()]
    return None


# ─── Funzione principale ─────────────────────────────────────────────────────


def process_rna_file(file_path: Path) -> Optional[RNAResult]:
    """
    Legge e processa un file XLSX o CSV scaricato dal portale RNA.

    Args:
        file_path: Path del file da processare

    Returns:
        RNAResult con i totali calcolati, oppure None in caso di file vuoto/errore.
    """
    logger.info("Processing file RNA: %s", file_path)

    # ── 1. Lettura file ───────────────────────────────────────────────────────
    try:
        ext = file_path.suffix.lower()
        if ext == ".xlsx":
            df = pd.read_excel(file_path, dtype=str)
        elif ext == ".csv":
            # Prova vari separatori (RNA usa ; o ,)
            for sep in [";", ",", "\t"]:
                try:
                    df = pd.read_csv(file_path, sep=sep, dtype=str, encoding="utf-8-sig")
                    if df.shape[1] > 1:
                        break
                except Exception:
                    continue
        else:
            logger.error("Formato file non supportato: %s", ext)
            return None
    except Exception as e:
        logger.error("Errore lettura file %s: %s", file_path, e)
        return None

    if df.empty:
        logger.warning("File RNA vuoto: %s", file_path)
        return None

    logger.info("File letto: %d righe, colonne: %s", len(df), list(df.columns))

    # ── 2. Identifica colonne chiave ─────────────────────────────────────────
    amount_col = _find_column(df, AMOUNT_COLS_CANDIDATES)
    date_col = _find_column(df, DATE_COLS_CANDIDATES)
    title_col = _find_column(df, TITLE_COLS_CANDIDATES)

    if not amount_col:
        logger.warning("Colonna importo non trovata! Colonne disponibili: %s", list(df.columns))
        # Ultima spiaggia: cerca colonne numeriche
        numeric_candidates = [c for c in df.columns if any(kw in c.lower() for kw in ["import", "element", "contribu", "valor"])]
        if numeric_candidates:
            amount_col = numeric_candidates[0]
            logger.info("Uso colonna importo alternativa: %r", amount_col)
        else:
            logger.error("Impossibile identificare colonna importo. Restituisco 0.")
            return RNAResult(0.0, 0.0, "Errore: colonna importo non trovata")

    logger.info("Colonne identificate → importo: %r | data: %r | titolo: %r",
                amount_col, date_col, title_col)

    # ── 3. Normalizza importi ─────────────────────────────────────────────────
    df["_amount"] = df[amount_col].apply(_normalize_amount)

    # ── 4. Normalizza date ────────────────────────────────────────────────────
    if date_col:
        df["_date"] = df[date_col].apply(_parse_date)
    else:
        df["_date"] = None
        logger.warning("Colonna data non trovata. Totale ultimi 3 anni = 0.")

    # ── 5. Calcola Totale Complessivo ─────────────────────────────────────────
    totale_contributi = df["_amount"].sum()
    logger.info("Totale contributi complessivo: %.2f", totale_contributi)

    # ── 6. Calcola Totale Ultimi 3 Anni ──────────────────────────────────────
    cutoff_date = datetime.now() - timedelta(days=DAYS_3_YEARS)
    if date_col:
        mask_3y = df["_date"].apply(lambda d: d is not None and d >= cutoff_date)
        totale_ultimi_3_anni = df.loc[mask_3y, "_amount"].sum()
    else:
        totale_ultimi_3_anni = 0.0
    logger.info("Totale ultimi 3 anni: %.2f", totale_ultimi_3_anni)

    # ── 7. Identificazione Ultimo Contributo ──────────────────────────────────
    ultimo_contributo = _find_last_contribution(df, date_col, title_col)
    logger.info("Ultimo contributo: %r", ultimo_contributo)

    return RNAResult(totale_contributi, totale_ultimi_3_anni, ultimo_contributo)


def _find_last_contribution(
    df: pd.DataFrame,
    date_col: Optional[str],
    title_col: Optional[str],
) -> str:
    """
    Trova il record con la data più recente e restituisce il titolo della misura.
    Se non ci sono date, restituisce il titolo dell'ultima riga.
    """
    if date_col and df["_date"].notna().any():
        # Trova indice della data massima
        valid_dates = df["_date"].dropna()
        if not valid_dates.empty:
            max_date_idx = valid_dates.idxmax()
            max_date = df.loc[max_date_idx, "_date"]
            date_str = max_date.strftime("%d/%m/%Y") if max_date else "N/D"

            if title_col and pd.notna(df.loc[max_date_idx, title_col]):
                title = str(df.loc[max_date_idx, title_col]).strip()
            else:
                # Fallback: prende la prima colonna testuale
                title = _get_first_text_value(df, max_date_idx)

            return f"{title} ({date_str})" if title else date_str

    # Nessuna data disponibile: prende l'ultima riga
    if title_col and not df.empty:
        last_row = df.iloc[-1]
        if pd.notna(last_row.get(title_col, None)):
            return str(last_row[title_col]).strip()

    return "N/D"


def _get_first_text_value(df: pd.DataFrame, idx: int) -> str:
    """Restituisce il valore della prima colonna testuale non vuota per un indice dato."""
    row = df.iloc[idx]
    for col in df.columns:
        val = row.get(col, None)
        if pd.notna(val) and str(val).strip() and col not in ["_amount", "_date"]:
            return str(val).strip()
    return ""


def cleanup_file(file_path: Path) -> None:
    """Elimina il file temporaneo dopo l'elaborazione."""
    try:
        if file_path.exists():
            os.remove(file_path)
            logger.debug("File temporaneo eliminato: %s", file_path)
    except Exception as e:
        logger.warning("Errore eliminazione file %s: %s", file_path, e)

