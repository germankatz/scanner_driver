import win32com.client
import pythoncom

def spy_dialog():
    pythoncom.CoInitialize()
    try:
        dialog = win32com.client.Dispatch("WIA.CommonDialog")
        device = dialog.ShowSelectDevice()
        
        if not device:
            print("Escáner no seleccionado.")
            return

        print("Leyendo estado inicial del escáner...")
        initial_props = {}
        for p in device.Properties:
            try:
                initial_props[p.PropertyID] = p.Value
            except:
                pass
                
        initial_items = {}
        for idx in range(1, device.Items.Count + 1):
            initial_items[idx] = {}
            for p in device.Items[idx].Properties:
                try:
                    initial_items[idx][p.PropertyID] = p.Value
                except:
                    pass

        print("\nAbriendo diálogo... POR FAVOR SELECCIONA 'PLANO' (CRISTAL) Y DALE A ACEPTAR/ESCANEAR.")
        try:
            # ShowSelectItems abre un diálogo donde puedes configurar cosas antes de transferir
            selected_items = dialog.ShowSelectItems(device)
        except Exception as e:
            print("El diálogo se canceló o falló:", e)
            return

        if not selected_items:
            print("No se seleccionó ningún item.")
            return

        print("\n--- CAMBIOS DETECTADOS DESPUÉS DEL DIÁLOGO ---")
        
        # Comparar Device Properties
        print("\n>> Cambios en Propiedades del Dispositivo:")
        for p in device.Properties:
            try:
                new_val = p.Value
                old_val = initial_props.get(p.PropertyID)
                if old_val != new_val:
                    print(f"Propiedad [{p.PropertyID}] {p.Name}: cambió de {old_val} ---> {new_val}")
            except:
                pass

        # Comparar Items
        print("\n>> Cambios en los Items:")
        for idx in range(1, device.Items.Count + 1):
            for p in device.Items[idx].Properties:
                try:
                    new_val = p.Value
                    old_val = initial_items[idx].get(p.PropertyID)
                    if old_val != new_val:
                        print(f"Item {idx} - Prop [{p.PropertyID}] {p.Name}: cambió de {old_val} ---> {new_val}")
                except:
                    pass

        print("\n>> PROPIEDADES FINALES DEL ITEM SELECCIONADO:")
        if selected_items:
            for idx in range(1, selected_items.Count + 1):
                item = selected_items[idx]
                print(f"Item Seleccionado {idx}:")
                for p in item.Properties:
                    try:
                        print(f"  [{p.PropertyID}] {p.Name}: {p.Value}")
                    except:
                        pass
        else:
            print("No hay items seleccionados.")

    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    spy_dialog()
