"""
BLE Provisioning Service for RK AI Assistant.
Uses dbus/bluez to advertise 'RK-AI-{SLUG}' and accept Wi-Fi credentials via Nordic UART Service.
"""

import sys
import dbus
import dbus.mainloop.glib
import dbus.service
import json
import threading
import time
from gi.repository import GLib
from .networking import apply_wifi_credentials, read_slug
from .config import BLUETOOTH_HCI

BLUEZ_SERVICE_NAME = 'org.bluez'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
AGENT_MANAGER_IFACE = 'org.bluez.AgentManager1'
AGENT_IFACE = 'org.bluez.Agent1'

LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'

# Nordic UART Service UUIDs
PROVISIONING_SVC_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
RX_CHRC_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'  # Write (Mobile -> Pi)
TX_CHRC_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'  # Notify (Pi -> Mobile)

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response

class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/rk_ai/service'
    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        return [chrc.get_path() for chrc in self.characteristics]

    def get_characteristics(self):
        return self.characteristics

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return []

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        pass

class RxCharacteristic(Characteristic):
    def __init__(self, bus, index, service, tx_characteristic):
        Characteristic.__init__(
            self, bus, index,
            RX_CHRC_UUID,
            ['write', 'write-without-response'],
            service)
        self.tx = tx_characteristic

    def WriteValue(self, value, options):
        try:
            json_str = bytearray(value).decode('utf-8')
            print(f"[ble] RX received {len(json_str)} bytes", flush=True)
            
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                print("[ble] Invalid JSON received", flush=True)
                self.tx.send_status("fail", "Invalid JSON")
                return

            ssid = data.get('ssid')
            password = data.get('password', data.get('pass', ''))
            
            if not ssid:
                print("[ble] Missing SSID in payload", flush=True)
                self.tx.send_status("fail", "Missing SSID")
                return

            print(f"[ble] Received Wi-Fi credentials for SSID: {ssid}", flush=True)
            
            # Application thread
            def apply_task():
                print(f"[ble] Applying credentials for {ssid}...", flush=True)
                success = apply_wifi_credentials(ssid, password or "")
                if success:
                    print(f"[ble] Successfully applied {ssid}", flush=True)
                    # Notify success on main loop
                    GLib.idle_add(self.tx.send_status, "ok")
                else:
                    print(f"[ble] Failed to apply {ssid}", flush=True)
                    GLib.idle_add(self.tx.send_status, "fail", "Apply failed")

            threading.Thread(target=apply_task, daemon=True).start()

        except Exception as e:
            print(f"[ble] RX error: {e}", flush=True)
            self.tx.send_status("fail", "Internal error")

class TxCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(
            self, bus, index,
            TX_CHRC_UUID,
            ['notify'],
            service)
        self.notifying = False

    def send_status(self, status, reason=None):
        if not self.notifying:
            print("[ble] TX not subscribed, skipping notification", flush=True)
            return
            
        payload = {"status": status}
        if reason:
            payload["reason"] = reason
            
        data = json.dumps(payload).encode('utf-8')
        value = dbus.Array([dbus.Byte(b) for b in data], signature='y')
        
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': value}, [])
        print(f"[ble] TX sent: {payload}", flush=True)

    @dbus.service.signal(DBUS_PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def StartNotify(self):
        print("[ble] TX StartNotify", flush=True)
        self.notifying = True

    def StopNotify(self):
        print("[ble] TX StopNotify", flush=True)
        self.notifying = False

class NoInputNoOutputAgent(dbus.service.Object):
    def __init__(self, bus, path):
        dbus.service.Object.__init__(self, bus, path)

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        if str(uuid).lower() == PROVISIONING_SVC_UUID:
            return
        raise dbus.exceptions.DBusException('org.bluez.Error.Rejected', 'Service not permitted')

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        print(f"[ble] Accepting authorization from {device}", flush=True)
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def Cancel(self, device):
        pass

class ProvisioningAdvertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/rk_ai/advertisement'
    def __init__(self, bus, index, local_name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.local_name = local_name
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            LE_ADVERTISEMENT_IFACE: {
                'Type': 'peripheral',
                'ServiceUUIDs': dbus.Array([PROVISIONING_SVC_UUID], signature='s'),
                'LocalName': dbus.String(self.local_name),
                'IncludeTxPower': dbus.Boolean(True)
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException('org.freedesktop.DBus.Error.UnknownInterface', '')
        return self.get_properties()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE)
    def Release(self):
        print(f'{self.path}: Released!')

def register_ad_cb(): print('[ble] Advertisement registered')
def register_ad_error_cb(error): print(f'[ble] Failed to register advertisement: {error}')
def register_app_cb(): print('[ble] GATT application registered')
def register_app_error_cb(error): print(f'[ble] Failed to register application: {error}')

def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    preferred, fallback = None, None
    
    for o, props in objects.items():
        if LE_ADVERTISING_MANAGER_IFACE in props and GATT_MANAGER_IFACE in props:
            if o.endswith(f'/{BLUETOOTH_HCI}'):
                preferred = o
                break
            if not fallback:
                fallback = o
    
    return preferred or fallback

def power_adapter(bus, adapter_path):
    adapter_props = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), DBUS_PROP_IFACE)
    print(f"[ble] Ensuring {adapter_path} is powered on...", flush=True)
    adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))
    adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(1))
    adapter_props.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(1))
    # Alias is helpful for some devices, but LocalName in Advert overrides it usually
    # adapter_props.Set('org.bluez.Adapter1', 'Alias', dbus.String(f'rk-ai-UNKNOWN')) 

def start_ble_service(slug):
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    # 1. Register Agent
    try:
        agent_path = "/org/bluez/rk_ai_agent"
        agent = NoInputNoOutputAgent(bus, agent_path)
        mgr = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"), AGENT_MANAGER_IFACE)
        # Attempt minimal cleanup if needed? No, just register.
        try:
             mgr.RegisterAgent(dbus.ObjectPath(agent_path), "NoInputNoOutput")
        except dbus.exceptions.DBusException as e:
             if 'AlreadyExists' in str(e):
                 pass # Warning: skipping re-registration
             else:
                 raise
        mgr.RequestDefaultAgent(dbus.ObjectPath(agent_path))
        print("[ble] Agent registered")
    except Exception as e:
        print(f"[ble] Agent setup warning: {e}")

    # 2. Setup Adapter
    adapter = find_adapter(bus)
    if not adapter:
        print("[ble] No adapter found!")
        return
        
    try:
        power_adapter(bus, adapter)
        adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)
        
        # 3. Setup GATT
        app = Application(bus)
        service = Service(bus, 0, PROVISIONING_SVC_UUID, True)
        
        tx = TxCharacteristic(bus, 0, service)
        rx = RxCharacteristic(bus, 1, service, tx)
        
        service.add_characteristic(tx)
        service.add_characteristic(rx)
        app.add_service(service)
        
        service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
        service_manager.RegisterApplication(app.get_path(), {},
                                            reply_handler=register_app_cb,
                                            error_handler=register_app_error_cb)

        # 4. Advertise
        ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)
        ad = ProvisioningAdvertisement(bus, 0, f"rk-ai-{slug}")
        ad_manager.RegisterAdvertisement(ad.get_path(), {},
                                         reply_handler=register_ad_cb,
                                         error_handler=register_ad_error_cb)

        print(f"[ble] Running provisioning service `rk-ai-{slug}` on {adapter}")
        mainloop = GLib.MainLoop()
        mainloop.run()

    except Exception as e:
        print(f"[ble] Critical error: {e}")
        # In production we might want to retry loop here

if __name__ == '__main__':
    slug, _ = read_slug()
    start_ble_service(slug or "000000000")
