"""
mailer.py - Modulo per l'invio di notifiche email.

Invia un'email riepilogativa quando vengono rilevati nuovi contributi
o aggiornamenti sui totali per le aziende.
"""

import json
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("PVT/mail_config.json")
TEMP_DATA_PATH = Path("PVT/last_email_data.json")

def save_email_data(updates_by_category: List[Tuple[str, List[Dict[str, str]]]]) -> None:
    """Salva i dati da inviare in un file JSON temporaneo."""
    try:
        TEMP_DATA_PATH.parent.mkdir(exist_ok=True)
        with open(TEMP_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(updates_by_category, f, indent=2, ensure_ascii=False)
        logger.info("Dati email salvati temporaneamente in %s", TEMP_DATA_PATH)
    except Exception as e:
        logger.error("Errore salvataggio dati email: %s", e)

def load_email_data() -> List[Tuple[str, List[Dict[str, str]]]]:
    """Carica i dati dal file JSON temporaneo."""
    if not TEMP_DATA_PATH.exists():
        logger.error("Nessun dato email precedente trovato in %s", TEMP_DATA_PATH)
        return []
    try:
        with open(TEMP_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Errore lettura dati email da %s: %s", TEMP_DATA_PATH, e)
        return []

def send_notification(updates_by_category: List[Tuple[str, List[Dict[str, str]]]]) -> None:
    """
    Invia un'email con l'elenco delle aziende aggiornate.
    """
    # Prima salviamo i dati nel json
    save_email_data(updates_by_category)

    if not CONFIG_PATH.exists():
        logger.error("File di configurazione mail non trovato: %s", CONFIG_PATH)
        return
        
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        smtp_server = config["smtp_server"]
        smtp_port = config["smtp_port"]
        sender_email = config["sender_email"]
        sender_password = config["sender_password"]
        recipient_email = config["recipient_email"]
        
        if sender_password == "INSERISCI_QUI_LA_TUA_PASSWORD":
            logger.warning("Password email non configurata in %s. Invio mail ignorato.", CONFIG_PATH)
            return

    except Exception as e:
        logger.error("Errore nella lettura di %s: %s", CONFIG_PATH, e)
        return

    # Costruisci il corpo del messaggio
    body_lines = ["Ciao,"]
    
    total_companies = sum(len(companies) for _, companies in updates_by_category)
    
    if total_companies == 0:
        body_lines.append("il bot RNAscraper ha completato la scansione odierna.")
        body_lines.append("Non sono stati rilevati nuovi contributi o aggiornamenti per nessuna azienda.")
        subject = "Notifica RNA: Scansione completata (nessuna novità)"
    else:
        body_lines.append("il bot RNAscraper ha completato la scansione e ha rilevato aggiornamenti sui contributi per le seguenti aziende:")
        body_lines.append("")
        
        for category, companies in updates_by_category:
            body_lines.append(f"=== Foglio: {category} ===")
            for comp in companies:
                ragione = comp.get("ragione", "Sconosciuta")
                ultimo = comp.get("ultimo_contributo", "N/D")
                totale = comp.get("totale", 0.0)
                cf = comp.get("cf", "N/D")
                
                body_lines.append(f"• Azienda: {ragione} (P.IVA: {cf})")
                body_lines.append(f"  Totale Contributi: € {totale:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                body_lines.append(f"  Ultimo Contributo: {ultimo}")
                body_lines.append("")

        subject = f"Notifica RNA: Aggiornamenti rilevati per {total_companies} aziende"

    body_lines.append("Puoi verificare i dettagli direttamente su Google Sheets.")
    body_lines.append("Saluti,\nIl Bot RNAscraper")
    
    msg_text = "\n".join(body_lines)
    
    msg = EmailMessage()
    msg.set_content(msg_text)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email

    # Allega i file Excel (se presenti)
    downloads_dir = Path("downloads")
    attached_files = set()
    
    if downloads_dir.exists():
        from enhance_excel import enhance_excel_with_deminimis
        for category, companies in updates_by_category:
            for comp in companies:
                cf = comp.get("cf")
                if cf:
                    enhance_excel_with_deminimis(cf, downloads_dir)
                    excel_path = downloads_dir / f"rna_{cf}.xlsx"
                    if not excel_path.exists():
                        excel_path = downloads_dir / f"deminimis_{cf}.xlsx"
                    if excel_path.exists() and excel_path not in attached_files:
                        try:
                            with open(excel_path, "rb") as f:
                                file_data = f.read()
                            msg.add_attachment(
                                file_data, 
                                maintype='application', 
                                subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
                                filename=excel_path.name
                            )
                            attached_files.add(excel_path)
                            logger.debug("Allegato %s alla mail.", excel_path.name)
                        except Exception as e:
                            logger.error("Errore nell'allegare %s: %s", excel_path, e)

    logger.info("Tentativo di invio email a %s tramite %s:%s...", recipient_email, smtp_server, smtp_port)
    try:
        # Usa SMTP_SSL dato che la porta è 465
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        logger.info("Email inviata con successo.")
    except Exception as e:
        logger.error("Errore durante l'invio dell'email: %s", e, exc_info=True)
