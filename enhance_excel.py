import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def enhance_excel_with_deminimis(cf: str, downloads_dir: Path):
    rna_xlsx = downloads_dir / f"rna_{cf}.xlsx"
    if not rna_xlsx.exists():
        return
        
    deminimis_csv = downloads_dir / f"deminimis_{cf}.csv"
    if not deminimis_csv.exists():
        deminimis_csv = downloads_dir / f"deminimis_{cf}.xlsx"
        if not deminimis_csv.exists():
            return
            
    try:
        if deminimis_csv.suffix == '.csv':
            try:
                df_dem = pd.read_csv(deminimis_csv, sep=',', dtype=str, encoding='utf-8-sig')
                if "COR" not in df_dem.columns:
                    df_dem = pd.read_csv(deminimis_csv, sep=';', dtype=str, encoding='utf-8-sig')
            except:
                df_dem = pd.read_csv(deminimis_csv, sep=';', dtype=str, encoding='utf-8-sig')
        else:
            df_dem = pd.read_excel(deminimis_csv, dtype=str)
            
        if "COR" not in df_dem.columns:
            logger.warning("Colonna COR non trovata in %s", deminimis_csv)
            return
            
        deminimis_cors = set(df_dem["COR"].dropna().astype(str).str.strip())
        
        df_rna = pd.read_excel(rna_xlsx, dtype=str)
        
        if "COR" not in df_rna.columns:
            logger.warning("Colonna COR non trovata in %s", rna_xlsx)
            return
            
        if "Tipo Misura" not in df_rna.columns:
            df_rna["Tipo Misura"] = "Regime di aiuti"
            
        def update_tipo(row):
            cor = str(row["COR"]).strip()
            if cor in deminimis_cors:
                return "De minimis"
            else:
                return "Regime di aiuti"
                
        df_rna["Tipo Misura"] = df_rna.apply(update_tipo, axis=1)
        
        df_rna.to_excel(rna_xlsx, index=False)
        logger.info("File %s aggiornato con il check De minimis", rna_xlsx.name)
        
    except Exception as e:
        logger.error("Errore durante l'aggiornamento dell'excel %s: %s", rna_xlsx.name, e)
