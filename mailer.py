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

def send_notification(updates_by_category: List[Tuple[str, List[Dict[str, str]]]]) -> None:
    """
    Invia un'email con l'elenco delle aziende aggiornate.
    
    Args:
        updates_by_category: Lista di tuple (Nome Categoria, Lista Dettagli Aziende)
                             es. [("Generale (RNA)", [{"ragione": "...", "totale": 100, ...}])]
    """
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
    body_lines = [
        "Ciao,",
        "il bot RNAscraper ha completato la scansione e ha rilevato aggiornamenti sui contributi per le seguenti aziende:",
        ""
    ]
    
    total_companies = 0
    
    for category, companies in updates_by_category:
        body_lines.append(f"=== Foglio: {category} ===")
        for comp in companies:
            ragione = comp.get("ragione", "Sconosciuta")
            ultimo = comp.get("ultimo_contributo", "N/D")
            totale = comp.get("totale", 0.0)
            
            body_lines.append(f"• Azienda: {ragione}")
            body_lines.append(f"  Totale Contributi: € {totale:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            body_lines.append(f"  Ultimo Contributo: {ultimo}")
            body_lines.append("")
            total_companies += 1
            
    if total_companies == 0:
        logger.info("Nessuna azienda da notificare via mail.")
        return

    body_lines.append("Puoi verificare i dettagli direttamente su Google Sheets.")
    body_lines.append("Saluti,\nIl Bot RNAscraper")
    
    msg_text = "\n".join(body_lines)
    
    msg = EmailMessage()
    msg.set_content(msg_text)
    msg["Subject"] = f"Notifica RNA: Aggiornamenti rilevati per {total_companies} aziende"
    msg["From"] = sender_email
    msg["To"] = recipient_email

    logger.info("Tentativo di invio email a %s tramite %s:%s...", recipient_email, smtp_server, smtp_port)
    try:
        # Usa SMTP_SSL dato che la porta è 465
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        logger.info("Email inviata con successo.")
    except Exception as e:
        logger.error("Errore durante l'invio dell'email: %s", e, exc_info=True)

