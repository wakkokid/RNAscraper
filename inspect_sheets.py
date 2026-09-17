"""
Script di ispezione del foglio Google Sheets per verificare struttura dei tab.
Richede OAuth interattivo al primo avvio.
"""
import gspread
import json
import sys

SPREADSHEET_ID = "1HVyQUbdGMRCBnzCO8r3sFLeAEO6sZF7VglZuQ6u3c6U"
CREDENTIALS_FILE = "PVT/client_secret_244769943975-b7i3r0hgpvhe3fcilsnua5r98cpe9mmb.apps.googleusercontent.com.json"
AUTHORIZED_USER_FILE = "PVT/authorized_user.json"


def inspect_sheets():
    print("[*] Connessione a Google Sheets via OAuth...")
    gc = gspread.oauth(
        credentials_filename=CREDENTIALS_FILE,
        authorized_user_filename=AUTHORIZED_USER_FILE,
    )

    print(f"[*] Apertura spreadsheet: {SPREADSHEET_ID}")
    sh = gc.open_by_key(SPREADSHEET_ID)

    worksheets = sh.worksheets()
    print(f"[*] Tab trovati: {[ws.title for ws in worksheets]}")

    # Ispezione tab "Aziende"
    print("\n--- TAB 'Aziende' ---")
    try:
        ws_aziende = sh.worksheet("Aziende")
        all_values = ws_aziende.get_all_values()
        print(f"  Righe totali: {len(all_values)}")
        if all_values:
            print(f"  Prima riga (header?): {all_values[0]}")
            if len(all_values) > 1:
                print(f"  Seconda riga (prima azienda?): {all_values[1]}")
            if len(all_values) > 2:
                print(f"  Terza riga: {all_values[2]}")
        else:
            print("  Il tab è VUOTO!")
    except gspread.WorksheetNotFound:
        print("  ERRORE: Tab 'Aziende' non trovato!")

    # Ispezione tab "RNA"
    print("\n--- TAB 'RNA' ---")
    try:
        ws_rna = sh.worksheet("RNA")
        all_values = ws_rna.get_all_values()
        print(f"  Tab 'RNA' esiste. Righe: {len(all_values)}")
        if all_values:
            print(f"  Prima riga: {all_values[0]}")
        else:
            print("  Il tab è vuoto (va inizializzato con intestazioni).")
    except gspread.WorksheetNotFound:
        print("  Tab 'RNA' NON ESISTE - va creato con le intestazioni corrette.")


if __name__ == "__main__":
    inspect_sheets()

