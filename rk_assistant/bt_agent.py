#!/usr/bin/env python3
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", out_signature="")
    def Release(self):
        print("[agent] Release", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[agent] Authorizing service {uuid} for {device} - Accepted", flush=True)
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        print(f"[agent] PIN Request for {device} - Auto-returning 0000", flush=True)
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[agent] Passkey Request for {device} - Auto-returning 0", flush=True)
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[agent] DisplayPasskey for {device}: {passkey:06d}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        print(f"[agent] DisplayPinCode for {device}: {pincode}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] RequestConfirmation for {device} (Code: {passkey:06d}) - AUTO ACCEPTED", flush=True)
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"[agent] RequestAuthorization for {device} - AUTO ACCEPTED", flush=True)
        return

    @dbus.service.method("org.bluez.Agent1", out_signature="")
    def Cancel(self):
        print("[agent] Cancel", flush=True)

if __name__ == '__main__':
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    
    agent_path = "/rk/ai/agent"
    agent = Agent(bus, agent_path)
    
    obj = bus.get_object("org.bluez", "/org/bluez")
    manager = dbus.Interface(obj, "org.bluez.AgentManager1")
    
    try:
        manager.UnregisterAgent(agent_path)
    except:
        pass
        
    # We use KeyboardDisplay as a middle ground: 
    # It allows phone-style "Just Works" (RequestConfirmation) 
    # AND speaker-style legacy PINs (RequestPinCode).
    manager.RegisterAgent(agent_path, "KeyboardDisplay")
    manager.RequestDefaultAgent(agent_path)
    print("[agent] RK AI 'Hybrid-Ready' Agent (KeyboardDisplay) registered...", flush=True)
    
    loop = GLib.MainLoop()
    loop.run()
