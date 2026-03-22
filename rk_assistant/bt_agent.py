#!/usr/bin/env python3
"""
RK AI Bluetooth Agent.

Handles pairing for both the Bluetooth speaker AND any phone that connects.
KEY CHANGE: AuthorizeService now REJECTS A2DP audio UUIDs from non-speaker
devices. This prevents the Pi from treating a connected phone as a speaker
and stops PulseAudio from switching the default sink away from our speaker.

Audio-related UUIDs blocked for non-speaker devices:
 - A2DP Sink:   0000110b (phone wants Pi to use it as speaker)
 - A2DP Source: 0000110a (Pi wants to use phone as speaker)
 - AVRCP:       0000110e / 0000110c
 - HFP/HSP:     0000111e / 00001108 (phone would become a headset/mic)
"""
import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# Load speaker MAC from env so we can still allow audio from/to it
_SPEAKER_MAC = os.getenv("BLUETOOTH_SPEAKER_MAC", "D0:78:1D:4F:F4:1E").lower()

# UUIDs that make the Pi route audio through a connected device.
# We block these for any device that is NOT our speaker.
_AUDIO_UUIDS = {
    "0000110a-0000-1000-8000-00805f9b34fb",  # A2DP Source (Pi → device)
    "0000110b-0000-1000-8000-00805f9b34fb",  # A2DP Sink   (device → Pi)
    "0000110c-0000-1000-8000-00805f9b34fb",  # AVRCP Target
    "0000110e-0000-1000-8000-00805f9b34fb",  # AVRCP Controller
    "0000111e-0000-1000-8000-00805f9b34fb",  # HFP (Hands-Free Profile)
    "00001108-0000-1000-8000-00805f9b34fb",  # HSP (Headset Profile)
}

def _mac_from_dbus_path(device_path: str) -> str:
    """Extract a lowercase MAC from a BlueZ device object path like /org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF."""
    # Last segment is dev_AA_BB_CC_DD_EE_FF
    parts = str(device_path).split("/")
    dev_part = parts[-1]  # e.g. dev_D0_78_1D_4F_F4_1E
    if dev_part.startswith("dev_"):
        return dev_part[4:].replace("_", ":").lower()
    return ""


class Agent(dbus.service.Object):

    @dbus.service.method("org.bluez.Agent1", out_signature="")
    def Release(self):
        print("[agent] Release", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        uuid_lower = str(uuid).lower()
        device_mac = _mac_from_dbus_path(device)

        if uuid_lower in _AUDIO_UUIDS and device_mac != _SPEAKER_MAC:
            print(
                f"[agent] 🚫 BLOCKED audio UUID {uuid} from non-speaker device {device_mac} "
                f"(speaker is {_SPEAKER_MAC})",
                flush=True,
            )
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Rejected",
                "Audio profiles are reserved for the dedicated speaker.",
            )

        print(f"[agent] ✅ Authorizing service {uuid} for {device_mac}", flush=True)
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

    manager.RegisterAgent(agent_path, "KeyboardDisplay")
    manager.RequestDefaultAgent(agent_path)
    print(
        f"[agent] RK AI Audio-Locked Agent registered. Speaker: {_SPEAKER_MAC}",
        flush=True,
    )

    loop = GLib.MainLoop()
    loop.run()
