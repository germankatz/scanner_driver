import win32com.client
import pythoncom

def intercept_wia():
    pythoncom.CoInitialize()
    try:
        print("Abriendo diálogo de selección de escáner...")
        dialog = win32com.client.Dispatch("WIA.CommonDialog")
        device = dialog.ShowSelectDevice()
        
        if not device:
            print("No se seleccionó ningún escáner.")
            return

        print(f"\nEscáner seleccionado: {device.Properties('Name').Value}")
        
        # 3088 = Document Handling Select
        try:
            doc_handling = device.Properties("3088")
            print(f"Valor actual de Origen (3088): {doc_handling.Value}")
            
            # WIA SubType: 1=Range, 2=List, 3=Flag
            if doc_handling.SubType == 2: # List
                print("Valores permitidos para Origen:")
                for i in range(1, doc_handling.SubTypeValues.Count + 1):
                    print(f" - {doc_handling.SubTypeValues(i)}")
            elif doc_handling.SubType == 3: # Flag (Bitmask)
                print(f"Valores permitidos (Bits): {doc_handling.SubTypeValues(1)}")
        except Exception as e:
            print("Este escáner no expone la propiedad 3088 a nivel Device.")

        print("\nRevisando los Items (Bandas/Funciones) del escáner:")
        for idx in range(1, device.Items.Count + 1):
            item = device.Items[idx]
            print(f"\n--- ITEM {idx} ---")
            for prop in item.Properties:
                # 6146 = Intent, 6147 = DPI H, 6148 = DPI V
                if prop.PropertyID in [3088, 6146, 6147, 6148, 4103]:
                    val = "<error>"
                    try:
                        val = prop.Value
                    except:
                        pass
                    print(f"[{prop.PropertyID}] {prop.Name}: {val}")

    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    intercept_wia()
