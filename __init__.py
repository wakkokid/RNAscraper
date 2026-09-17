"""
RNAscraper - Automazione lettura aiuti di Stato dal portale RNA
e sincronizzazione su Google Sheets.

Struttura moduli:
  - sheets_client.py  : integrazione Google Sheets (gspread OAuth)
  - rna_scraper.py    : automazione Playwright per il portale RNA
  - data_processor.py : parsing e calcoli pandas sui file scaricati
  - sync_engine.py    : logica di confronto e aggiornamento RNA tab
  - main.py           : entry point
"""

