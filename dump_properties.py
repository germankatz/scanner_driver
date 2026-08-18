import win32com.client
import pythoncom

def dump_wia_properties():
    pythoncom.CoInitialize()
    try:
        dev_manager = win32com.client.Dispatch("WIA.DeviceManager")
        if dev_manager.DeviceInfos.Count == 0:
            print("No scanners found.")
            return

        for i in range(1, dev_manager.DeviceInfos.Count + 1):
            dev_info = dev_manager.DeviceInfos(i)
            if dev_info.Type == 1: # Scanner
                name = "Unknown"
                for p in dev_info.Properties:
                    if p.Name == "Name":
                        name = p.Value
                        break
                print(f"--- Scanner: {name} ---")
                
                device = dev_info.Connect()
                print("Device Properties:")
                for prop in device.Properties:
                    try:
                        print(f"  ID: {prop.PropertyID}, Name: {prop.Name}, Value: {prop.Value}")
                    except Exception as e:
                        print(f"  ID: {prop.PropertyID}, Name: {prop.Name}, Value: <could not read>")
                
                print("\nItem Properties:")
                for item_idx in range(1, device.Items.Count + 1):
                    item = device.Items(item_idx)
                    print(f" Item {item_idx}:")
                    for prop in item.Properties:
                        try:
                            print(f"  ID: {prop.PropertyID}, Name: {prop.Name}, Value: {prop.Value}")
                        except Exception as e:
                            print(f"  ID: {prop.PropertyID}, Name: {prop.Name}, Value: <could not read>")
                print("-" * 40)
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    dump_wia_properties()
