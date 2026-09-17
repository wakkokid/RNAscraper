# RNAscraper

Automazione Python per:
1. Lettura aziende da Google Sheets (tab **Aziende**)
2. Ricerca aiuti di Stato sul [portale RNA](https://www.rna.gov.it/trasparenza/aiuti) per Codice Fiscale
3. Calcolo totali e sincronizzazione risultati sul tab **RNA** dello stesso foglio

---

## Struttura progetto

```
RNAscraper/
├── main.py              # Entry point - orchestrazione completa
├── sheets_client.py     # Integrazione Google Sheets (gspread OAuth)
├── rna_scraper.py       # Automazione Playwright portale RNA
├── data_processor.py    # Parsing pandas + calcoli importi/date
├── sync_engine.py       # Logica confronto e costruzione batch aggiornamenti
├── requirements.txt     # Dipendenze Python
├── pyproject.toml       # Config uv
├── PVT/
│   ├── client_secret_*.json   # Credenziali OAuth Google (NON versionare!)
│   └── authorized_user.json   # Token OAuth salvato dopo primo login (auto-generato)
└── .venv/               # Virtual environment (uv)
```

---

## Setup iniziale

### 1. Prerequisiti
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installato

### 2. Installazione dipendenze

```powershell
# Installa dipendenze nel venv (già creato)
uv pip install -r requirements.txt

# Installa browser Chromium per Playwright
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 3. Prima autenticazione Google

Al primo avvio, il browser si aprirà per l'autorizzazione OAuth.
Il token verrà salvato in `PVT/authorized_user.json` per i run successivi.

```powershell
# Test connessione Google Sheets
uv run python inspect_sheets.py
```

---

## Utilizzo

### Esecuzione normale (headless)

```powershell
uv run python main.py
```

### Modalità debug (browser visibile)

```powershell
uv run python main.py --headless-off
```

### Dry-run (solo log, nessuna scrittura su Sheets)

```powershell
uv run python main.py --dry-run
```

### Processa solo alcuni CF

```powershell
uv run python main.py --only-cf "RSSMRA80A01H501U,12345678901"
```

### Log dettagliato (DEBUG)

```powershell
uv run python main.py --verbose
```

---

## Struttura tab Google Sheets

### Tab "Aziende" (INPUT - non modificare le prime 2 colonne)

| A (Ragione Sociale) | B (Codice Fiscale / P.IVA) |
|---|---|
| Esempio S.r.l. | 12345678901 |
| Altra Azienda S.p.A. | RSSMRA80A01H501U |

> ⚠️ I CF/P.IVA sono trattati sempre come **stringhe** (gli zeri iniziali vengono preservati).

### Tab "RNA" (OUTPUT - aggiornato automaticamente)

| Azienda | Codice Fiscale | Totale Contributi | Totale Ultimi 3 Anni | Ultimo Contributo Ricevuto | Data Ultimo Controllo | Novità |
|---|---|---|---|---|---|---|
| Esempio S.r.l. | 12345678901 | 50000.00 | 25000.00 | Misura XY (15/03/2024) | 2026-09-16 | Nuovo inserimento |

**Valori possibili per "Novità":**
- `Nuovo inserimento` — azienda non era presente nel tab RNA
- `Sì - Totali aggiornati` — i totali sono cambiati rispetto al precedente controllo
- `No` — nessuna variazione rilevata

---

## Logica di calcolo

| Campo | Calcolo |
|---|---|
| **Totale Contributi** | Somma di tutti gli importi registrati su RNA |
| **Totale Ultimi 3 Anni** | Somma importi con data concessione > oggi - 1095 giorni |
| **Ultimo Contributo Ricevuto** | Titolo misura con la data di concessione più recente |

---

## Log

Lo script salva i log in `rna_scraper.log` nella stessa cartella.
I log mostrano: aziende elaborate, importi trovati, errori per singola azienda (lo script non si blocca in caso di errore su una singola azienda).

---

## Sicurezza

> ⚠️ La cartella `PVT/` contiene credenziali sensibili ed è esclusa dal `.gitignore`.
> Non condividere mai i file `client_secret_*.json` e `authorized_user.json`.

