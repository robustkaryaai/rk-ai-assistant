#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[agent] AuthorizeService ({device}, {uuid}) - Accepted")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"[agent] RequestPinCode ({device}) - Auto returning 0000")
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[agent] RequestPasskey ({device}) - Auto returning 0")
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[agent] DisplayPasskey ({device}, {passkey:06d} entered {entered})")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"[agent] DisplayPinCode ({device}, {pincode})")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] RequestConfirmation for {device} (code {passkey:06d}) - Auto Accepted (Just Works)", flush=True)
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"[agent] RequestAuthorization for {device} - Auto Accepted", flush=True)
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[agent] RequestPasskey for {device} - Returning 0", flush=True)
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"[agent] RequestPinCode for {device} - Returning 0000", flush=True)
        return "0000"

    @dbus.service.method("org.bluez.Agent1", out_signature="")
    def Cancel(self):
        print("Cancel")

if __name__ == '__main__':
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    agent = Agent(bus, "/test/agent")
    
    obj = bus.get_object("org.bluez", "/org/bluez")
    manager = dbus.Interface(obj, "org.bluez.AgentManager1")
    
    # We register as NoInputNoOutput so phones don't ask for PINs,
    # but if they do, this script automatically accepts them anyway.
    manager.RegisterAgent("/test/agent", "NoInputNoOutput")
    manager.RequestDefaultAgent("/test/agent")
    print("Agent registered and running...")
    
    loop = GLib.MainLoop()
    loop.run()
