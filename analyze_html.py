import re

with open('rna_page_dump.html', encoding='utf-8') as f:
    html = f.read()

# Cerca tabella risultati con id
table_matches = re.findall(r'<table[^>]+id="([^"]+)"', html)
print('Tables con id:', table_matches[:20])

# Cerca link/pulsante export/download
export_matches = re.findall(r'href="([^"]*(?:export|download|csv|xlsx|esporta)[^"]*)"', html, re.I)
print('Export links:', export_matches[:10])

# Cerca elementi con class/id correlati a export
export_elem = re.findall(r'<[^>]+(?:id|class)="[^"]*(?:export|download|esporta)[^"]*"[^>]*>', html, re.I)
print('Export elements:', export_elem[:10])

# Cerca div/section con risultati
result_divs = re.findall(r'<[^>]+id="([^"]*(?:result|lista|aiuti|table)[^"]*)"', html, re.I)
print('Result divs:', result_divs[:10])

# Cerca msg nessun risultato
nessun = re.findall(r'[Nn]essun[^<]{0,100}', html)
print('Nessun risultato pattern:', nessun[:5])

# Cerca bottoni con icone/testi di esportazione
export_btns = re.findall(r'<(?:a|button)[^>]+>([^<]*(?:[Ee]sporta|[Dd]ownload|CSV|XLSX|[Ss]carica)[^<]*)<', html)
print('Export buttons text:', export_btns[:10])

