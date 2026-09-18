"""
sync_engine.py - Logica di confronto e sincronizzazione dei dati RNA su Google Sheets.

Responsabilità:
  - Confronto tra stato precedente (tab RNA) e nuovi dati calcolati
  - Rilevamento variazioni (novità) con tolleranza centesimale
  - Costruzione batch di righe da scrivere sul tab RNA
  - Gestione memoria storica (chiave primaria = Codice Fiscale)
"""

import logging
import math
from datetime import datetime
from typing import Optional

from data_processor import RNAResult

logger = logging.getLogger(__name__)

# Tolleranza per il confronto importi (€0.02 → margine di arrotondamento)
AMOUNT_TOLERANCE = 0.02

# Formato data per il campo "Data Ultimo Controllo"
DATE_FORMAT = "%Y-%m-%d"


# ─── Funzioni private ────────────────────────────────────────────────────────


def _parse_amount_str(s: str) -> float:
    """Parsa un importo stringa dal foglio (può avere formato euro italiano)."""
    if not s or s.strip() in ("", "-", "N/D", "0", "0.0", "0,00"):
        return 0.0
    s = str(s).strip()
    # Gestione formato italiano (1.234,56) → float
    s = s.replace("€", "").replace(" ", "").replace("\xa0", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _amounts_differ(old_str: str, new_value: float) -> bool:
    """
    Confronta un importo esistente (stringa) con il nuovo valore (float).
    Restituisce True se differiscono oltre la tolleranza.
    """
    old_value = _parse_amount_str(old_str)
    return abs(old_value - new_value) > AMOUNT_TOLERANCE


def _format_amount(value: float) -> str:
    """Formatta un float come stringa con 2 decimali (es. '1234.56')."""
    return f"{value:.2f}"


def _today_str() -> str:
    """Restituisce la data odierna nel formato definito in DATE_FORMAT."""
    return datetime.now().strftime(DATE_FORMAT)


# ─── Funzione principale ─────────────────────────────────────────────────────


def build_rna_rows(
    aziende: list[dict],
    results: dict[str, Optional[RNAResult]],
    existing_rna: dict[str, dict],
    scraped_cfs: set[str],
) -> list[list]:
    """
    Costruisce la lista completa di righe per il tab RNA, pronta per il batch update.

    Per ogni azienda nel tab "Aziende":
      - Se l'azienda non è ancora stata analizzata in questa sessione (non in scraped_cfs),
        ripristina lo stato precedente da existing_rna.
      - Se analizzata e CF non era presente in RNA → "Nuovo inserimento"
      - Se analizzata e totali differiscono → "Sì - Totali aggiornati"
      - Se analizzata e totali identici → "No"

    Args:
        aziende: lista di dict {'ragione_sociale', 'codice_fiscale'} dal tab Aziende
        results: dict CF → RNAResult|None (None = nessun aiuto o errore)
        existing_rna: dict CF → dict (stato precedente tab RNA)
        scraped_cfs: set di CF già elaborati nel run corrente

    Returns:
        Lista di righe [Azienda, CF, Totale, Ultimi3a, Ultimo, Data, Novità]
    """
    output_rows: list[list] = []
    today = _today_str()

    for azienda in aziende:
        cf = azienda["codice_fiscale"]
        ragione = azienda["ragione_sociale"]

        # Se non l'abbiamo ancora elaborata in questa sessione, manteniamo i dati vecchi
        if cf not in scraped_cfs:
            old = existing_rna.get(cf, {})
            # Se non c'era neanche prima, creiamo una riga vuota
            cf_val = str(cf).lstrip("'")
            totale_val = _parse_amount_str(old.get("totale_contributi", "0"))
            ultimi_3a_val = _parse_amount_str(old.get("totale_ultimi_3_anni", "0"))
            row = [
                ragione,
                cf_val,
                round(totale_val, 2),
                round(ultimi_3a_val, 2),
                old.get("ultimo_contributo", ""),
                old.get("data_controllo", ""),
                old.get("novita", ""),
            ]
            output_rows.append(row)
            continue

        result: Optional[RNAResult] = results.get(cf)

        # ── Calcola valori da scrivere (Azienda elaborata) ──────────────────
        if result is None:
            # Nessun aiuto registrato o errore di scraping
            new_totale = 0.0
            new_ultimi_3a = 0.0
            new_ultimo = "Nessun aiuto registrato"
        else:
            new_totale = result.totale_contributi
            new_ultimi_3a = result.totale_ultimi_3_anni
            new_ultimo = result.ultimo_contributo

        # ── Determina Novità ────────────────────────────────────────────────
        if cf not in existing_rna:
            novita = "Nuovo inserimento"
            logger.info("CF=%s → NUOVO INSERIMENTO", cf)
        else:
            old = existing_rna[cf]
            totale_changed = _amounts_differ(old.get("totale_contributi", "0"), new_totale)
            ultimi_changed = _amounts_differ(old.get("totale_ultimi_3_anni", "0"), new_ultimi_3a)

            if totale_changed or ultimi_changed:
                novita = "Sì - Totali aggiornati"
                logger.info(
                    "CF=%s → AGGIORNATO (vecchio totale=%s → nuovo=%.2f, "
                    "vecchio 3a=%s → nuovo=%.2f)",
                    cf,
                    old.get("totale_contributi", "N/D"),
                    new_totale,
                    old.get("totale_ultimi_3_anni", "N/D"),
                    new_ultimi_3a,
                )
            else:
                novita = "No"
                logger.debug("CF=%s → Nessuna variazione.", cf)

        # ── Costruisci riga ─────────────────────────────────────────────────
        # Con value_input_option="RAW", le stringhe non vengono parsate in numeri,
        # quindi gli zeri iniziali del CF sono preservati senza bisogno del prefisso "'"
        # e i float vengono passati come valori numerici corretti.
        cf_val = str(cf).lstrip("'")
        totale_val = round(float(new_totale), 2)
        ultimi_3a_val = round(float(new_ultimi_3a), 2)

        row = [
            ragione,
            cf_val,
            totale_val,
            ultimi_3a_val,
            new_ultimo,
            today,
            novita,
        ]
        output_rows.append(row)

    return output_rows


def summarize_changes(rows: list[list]) -> dict:
    """
    Genera un riepilogo delle modifiche effettuate.

    Returns:
        dict con statistiche: nuovi, aggiornati, invariati e dettagli_aggiornati
    """
    stats = {
        "nuovi": 0, 
        "aggiornati": 0, 
        "invariati": 0, 
        "totale": len(rows),
        "dettagli_aggiornati": []
    }
    
    for row in rows:
        novita = row[6] if len(row) > 6 else ""
        ragione = row[0] if len(row) > 0 else "Sconosciuta"
        totale = float(row[2]) if len(row) > 2 else 0.0
        ultimo_contributo = row[4] if len(row) > 4 else "N/D"
        
        dettaglio = {
            "ragione": ragione,
            "cf": row[1] if len(row) > 1 else "",
            "totale": totale,
            "ultimo_contributo": ultimo_contributo
        }
        
        if novita == "Nuovo inserimento":
            stats["nuovi"] += 1
            # Segnala come aggiornamento anche i nuovi inserimenti se hanno dei contributi
            if totale > 0:
                stats["dettagli_aggiornati"].append(dettaglio)
        elif "aggiornati" in novita.lower():
            stats["aggiornati"] += 1
            stats["dettagli_aggiornati"].append(dettaglio)
        else:
            stats["invariati"] += 1
            
    return stats

