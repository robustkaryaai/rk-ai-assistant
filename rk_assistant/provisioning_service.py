"""
BLE Provisioning Service for RK AI Assistant.
Uses dbus/bluez to advertise 'RK-AI-{SLUG}' and accept Wi-Fi credentials.
"""

import sys
import dbus
import dbus.mainloop.glib
import dbus.service
import json
from gi.repository import GLib
from .networking import apply_wifi_credentials, read_slug, post_audio_to_backend
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

# Nordic UART Service UUIDs (compatible with mobile client)
# Service (NUS)
PROVISIONING_SVC_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
# RX Characteristic (Write to device)
CREDENTIALS_CHRC_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'

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
    PATH_BASE = '/org/bluez/example/service'
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
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

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
        # Default empty read
        return []

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        # Override this
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        pass

class CredentialsChrc(Characteristic):
    def __init__(self, bus, index, service):
        Characteristic.__init__(
                self, bus, index,
                CREDENTIALS_CHRC_UUID,
                ['write', 'write-without-response'],
                service)

    def WriteValue(self, value, options):
        # Convert dbus bytes to string
        try:
            json_str = bytearray(value).decode('utf-8')
            print(f"[ble] Received credentials data: {json_str}", flush=True)
            data = json.loads(json_str)
            ssid = data.get('ssid')
            # Accept both 'password' and 'pass' keys from client
            password = data.get('password', data.get('pass', ''))
            
            if ssid:
                print(f"[ble] Applying WiFi: SSID={ssid}", flush=True)
                success = apply_wifi_credentials(ssid, password or "")
                if success:
                    print("[ble] WiFi credentials applied successfully.", flush=True)
                else:
                    print("[ble] Failed to apply WiFi credentials.", flush=True)
            else:
                 print("[ble] Invalid JSON: missing 'ssid'", flush=True)

        except Exception as e:
            print(f"[ble] Error processing write: {e}", flush=True)

class NoInputNoOutputAgent(dbus.service.Object):
    def __init__(self, bus, path):
        dbus.service.Object.__init__(self, bus, path)
        self.path = path

    @dbus.service.method(AGENT_IFACE)
    def Release(self):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def AuthorizeService(self, device, uuid):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        return dbus.String("0000")

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature='os', out_signature='')
    def DisplayPinCode(self, device, pincode):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device, passkey, entered):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device, passkey):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device):
        return

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='')
    def Cancel(self, device):
        return

class ProvisioningAdvertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'
    def __init__(self, bus, index, advertising_type, local_name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [PROVISIONING_SVC_UUID]
        self.local_name = local_name
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        properties['LocalName'] = dbus.String(self.local_name)
        properties['IncludeTxPower'] = dbus.Boolean(self.include_tx_power)
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                'org.freedesktop.DBus.Error.UnknownInterface',
                'The object does not implement the requested interface')
        return self.get_properties()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE)
    def Release(self):
        print(f'{self.path}: Released!')

def register_ad_cb():
    print('[ble] Advertisement registered')

def register_ad_error_cb(error):
    print(f'[ble] Failed to register advertisement: {error}')

def register_app_cb():
    print('[ble] GATT application registered')

def register_app_error_cb(error):
    print(f'[ble] Failed to register application: {error}')

# --- MODIFIED: Added adapter_name argument to target a specific HCI ---
def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()
    preferred = None
    fallback = None
    for o, props in objects.items():
        if LE_ADVERTISING_MANAGER_IFACE in props and GATT_MANAGER_IFACE in props:
            if o.endswith(f'/{BLUETOOTH_HCI}'):
                preferred = o
                break
            if not fallback:
                fallback = o
    return preferred or fallback
# --- END MODIFIED ---

def start_ble_service(slug):
    """Entry point to run the BLE loop. Blocking call!"""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    try:
        agent_path = "/org/bluez/rk_ai_agent"
        agent = NoInputNoOutputAgent(bus, agent_path)
        mgr = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"), AGENT_MANAGER_IFACE)
        mgr.RegisterAgent(dbus.ObjectPath(agent_path), "DisplayYesNo")
        mgr.RequestDefaultAgent(dbus.ObjectPath(agent_path))
        print("[ble] Pairing agent registered (DisplayYesNo)")
    except Exception as e:
        print(f"[ble] Failed to register agent: {e}")
    
    adapter = find_adapter(bus)
    
    if not adapter:
        print('[ble] No BLE adapter found')
        return

    adapter_obj = bus.get_object(BLUEZ_SERVICE_NAME, adapter)
    adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
    
    # Ensure powered on
    adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))
    # Make device visible so users can find it; agent enforces NoInputNoOutput
    adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(1))
    # Allow BLE pairing/bonding for GATT (agent enforces NoInputNoOutput)
    adapter_props.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(1))
    adapter_props.Set('org.bluez.Adapter1', 'Alias', dbus.String(f'rk-ai-{slug}'))

    service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

    app = Application(bus)
    prov_service = Service(bus, 0, PROVISIONING_SVC_UUID, True)
    prov_service.add_characteristic(CredentialsChrc(bus, 0, prov_service))
    app.add_service(prov_service)

    service_manager.RegisterApplication(app.get_path(), {},
                                        reply_handler=register_app_cb,
                                        error_handler=register_app_error_cb)

    ad = ProvisioningAdvertisement(bus, 0, 'peripheral', f'rk-ai-{slug}')
    ad_manager.RegisterAdvertisement(ad.get_path(), {},
                                     reply_handler=register_ad_cb,
                                     error_handler=register_ad_error_cb)

    print(f'[ble] Serving GATT for RK-AI-{slug} on adapter {adapter}...')
    
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        ad_manager.UnregisterAdvertisement(ad.get_path())
        sys.exit(0)

if __name__ == '__main__':
    # Test run
    slug, _ = read_slug()
    if not slug:
        slug = "000000000"
    start_ble_service(slug)
