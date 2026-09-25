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
from string import Template
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
        sender_name = config.get("sender_name", "BOT notifiche RNA")
        recipient_email = config["recipient_email"]
        gsheet_link = config.get("gsheet_link", "")
        
        # Lettura template (con fallback ai default hardcoded se mancano)
        mail_subj = config.get("mail_subj", "Notifica RNA: Aggiornamenti rilevati per $totale_aziende aziende")
        mail_header = config.get("mail_header", "Ciao,\nil bot RNAscraper ha completato la scansione e ha rilevato aggiornamenti per le seguenti aziende:\n\n")
        mail_company_template = config.get(
            "mail_company_template", 
            "=== Foglio: $foglio ===\n• Azienda: $ragione_sociale (P.IVA: $cf)\n  Totale Contributi: $totale (di cui ultimi 3 anni: $totale3y)\n  Ultimo Contributo: $ultimo_contributo\n\n"
        )
        mail_footer = config.get("mail_footer", "Puoi verificare i dettagli direttamente su Google Sheets.\nSaluti,\nIl Bot RNAscraper")
        mail_subj_no_updates = config.get("mail_subj_no_updates", "Notifica RNA: Scansione completata (nessuna novità)")
        mail_header_no_updates = config.get("mail_header_no_updates", "Ciao,\nil bot RNAscraper ha completato la scansione odierna.\nNon sono stati rilevati nuovi contributi o aggiornamenti per nessuna azienda.\n\n")
        
        if sender_password == "INSERISCI_QUI_LA_TUA_PASSWORD":
            logger.warning("Password email non configurata in %s. Invio mail ignorato.", CONFIG_PATH)
            return

    except Exception as e:
        logger.error("Errore nella lettura di %s: %s", CONFIG_PATH, e)
        return

    # Costruisci il corpo del messaggio
    from datetime import datetime
    data_odierna = datetime.now().strftime("%d/%m/%Y")
    
    total_companies = sum(len(companies) for _, companies in updates_by_category)
    
    if total_companies == 0:
        subject = Template(mail_subj_no_updates).safe_substitute(data_odierna=data_odierna)
        msg_text = Template(mail_header_no_updates).safe_substitute(data_odierna=data_odierna)
    else:
        subject = Template(mail_subj).safe_substitute(
            totale_aziende=total_companies,
            data_odierna=data_odierna
        )
        
        header_text = Template(mail_header).safe_substitute(
            totale_aziende=total_companies,
            data_odierna=data_odierna
        )
        
        companies_text = ""
        for category, companies in updates_by_category:
            for comp in companies:
                ragione = comp.get("ragione", "Sconosciuta")
                ultimo = comp.get("ultimo_contributo", "N/D")
                totale = comp.get("totale", 0.0)
                ultimi_3a = comp.get("ultimi_3a", 0.0)
                cf = comp.get("cf", "N/D")
                variazione = comp.get("variazione", 0.0)
                
                if variazione < -0.02:
                    ultimo = "Si è liberato parte del deminimis per scadenza dei 3 anni"
                
                tot_str = f"€ {totale:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                u3a_str = f"€ {ultimi_3a:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                var_str = f"€ {variazione:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if variazione > 0:
                    var_str = "+ " + var_str
                
                comp_text = Template(mail_company_template).safe_substitute(
                    foglio=category,
                    ragione_sociale=ragione,
                    cf=cf,
                    totale=tot_str,
                    totale3y=u3a_str,
                    ultimo_contributo=ultimo,
                    variazione=var_str
                )
                companies_text += comp_text

        footer_text = Template(mail_footer).safe_substitute(
            totale_aziende=total_companies,
            data_odierna=data_odierna
        )
        
        msg_text = header_text + companies_text + footer_text

    
    msg = EmailMessage()
    msg.set_content(msg_text)
    
    if gsheet_link:
        msg_html = msg_text.replace("\n", "<br>")
        msg_html = msg_html.replace("Google Sheets", f'<a href="{gsheet_link}">Google Sheets</a>')
        html_content = f"<html><body>{msg_html}</body></html>"
        msg.add_alternative(html_content, subtype='html')
        
    from email.utils import formataddr
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender_email))
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
