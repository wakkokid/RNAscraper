from sheets_client import get_client, open_spreadsheet

gc = get_client()
sh = open_spreadsheet(gc)
ws = sh.worksheet("RNA")
ws.update(range_name="K1:K4", values=[[1234.56], ["1234,56"], [789.12], ["789,12"]], value_input_option="USER_ENTERED")
ws.update(range_name="L1:L4", values=[[1234.56], ["1234,56"], [789.12], ["789,12"]], value_input_option="RAW")

