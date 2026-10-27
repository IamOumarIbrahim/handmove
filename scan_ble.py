import asyncio
from bleak import BleakScanner, BleakClient

async def main():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover(timeout=5.0)
    hiwonder_dev = None
    for d in devices:
        print(f"  {d.address}: {d.name}")
        if d.name and "hiwonder" in d.name.lower():
            hiwonder_dev = d
            
    if not hiwonder_dev:
        print("Looking for address 48:87:2D:82:90:58 directly...")
        # Check by MAC
        for d in devices:
            if "48:87:2D:82:90:58".lower() in d.address.lower():
                hiwonder_dev = d
                break

    if hiwonder_dev:
        print(f"[FOUND] Connecting to {hiwonder_dev.name} ({hiwonder_dev.address})...")
        async with BleakClient(hiwonder_dev) as client:
            print(f"[CONNECTED] Connected: {client.is_connected}")
            print("Services and Characteristics:")
            for s in client.services:
                print(f"  Service: {s.uuid}")
                for c in s.characteristics:
                    print(f"    Char: {c.uuid} | Properties: {c.properties}")
    else:
        print("[NOT FOUND] Hiwonder BLE device not found in active scan.")

if __name__ == "__main__":
    asyncio.run(main())
