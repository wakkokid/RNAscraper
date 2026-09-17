from sheets_client import get_client, open_spreadsheet

gc = get_client()
sh = open_spreadsheet(gc)
ws = sh.worksheet("RNA")
k = ws.get("K1:K4", value_render_option="UNFORMATTED_VALUE")
l = ws.get("L1:L4", value_render_option="UNFORMATTED_VALUE")

print("USER_ENTERED:")
print(k)

print("\nRAW:")
print(l)

