"""
Hardware Reset Monitor for RK AI Assistant.
Listens on GPIO 17 (pin 11).
If the button is held for 5 seconds, it deletes all saved Wi-Fi connections
and reboots the device, forcing it back into AP Provisioning mode.
"""

import os
import time
import threading
import subprocess

RESET_GPIO_PIN = 17
HOLD_TIME_SECONDS = 5

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("[reset_monitor] RPi.GPIO not available. Hardware reset button disabled.")

def perform_factory_reset():
    """Deletes all NetworkManager Wi-Fi connections and reboots."""
    print("[reset_monitor] 🚨 FACTORY RESET TRIGGERED! Deleting Wi-Fi credentials...", flush=True)
    
    # Try to play a sound or speak so user knows it worked
    try:
        from .audio_utils_simple import speak
        speak("Factory reset triggered. Erasing network settings and restarting.")
    except Exception as e:
        print(f"[reset_monitor] Note: could not play audio: {e}")
        
    # Delete all nmcli wifi connections
    try:
        result = subprocess.run(
            "nmcli -t -f UUID,TYPE connection show | grep 802-11-wireless | cut -d: -f1",
            shell=True, capture_output=True, text=True
        )
        uuids = result.stdout.strip().split('\n')
        
        for uuid in uuids:
            if uuid:
                print(f"[reset_monitor] Deleting connection UUID: {uuid}")
                subprocess.run(f"nmcli connection delete {uuid}", shell=True)
                
        print("[reset_monitor] Wi-Fi erased. Rebooting in 3 seconds...", flush=True)
        time.sleep(3)
        os.system("sudo reboot")
    except Exception as e:
        print(f"[reset_monitor] Error running nmcli: {e}")


def reset_button_loop():
    """Background loop polling the reset button state."""
    if not GPIO_AVAILABLE:
        return
        
    try:
        GPIO.setmode(GPIO.BCM)
        # Use internal pull-up resistor. Button should connect GPIO 17 to Ground.
        GPIO.setup(RESET_GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    except Exception as e:
        print(f"[reset_monitor] Failed to acquire GPIO pin (busy/locked): {e}. Disabling hardware button.")
        return
        
    
    print(f"[reset_monitor] Listening for 5-second hold on GPIO {RESET_GPIO_PIN}...", flush=True)
    
    button_pressed_time = 0
    is_pressed = False
    
    while True:
        try:
            # GPIO is LOW when pressed (because of pull-up resistor grounding)
            current_state = GPIO.input(RESET_GPIO_PIN) == GPIO.LOW
            
            if current_state and not is_pressed:
                # Button just pressed down
                is_pressed = True
                button_pressed_time = time.time()
                print("[reset_monitor] Button pressed. Hold for 5 seconds to reset...", flush=True)
                
            elif current_state and is_pressed:
                # Button is being held
                hold_duration = time.time() - button_pressed_time
                if hold_duration >= HOLD_TIME_SECONDS:
                    perform_factory_reset()
                    # Sleep forever to prevent double-triggering before reboot
                    time.sleep(9999)
                    
            elif not current_state and is_pressed:
                # Button released early
                is_pressed = False
                print("[reset_monitor] Button released. Reset cancelled.", flush=True)
                
            time.sleep(0.1) # Check 10 times a second
            
        except Exception as e:
            print(f"[reset_monitor] Error in loop: {e}")
            time.sleep(5)


def start_reset_monitor():
    """Spawns the hardware reset monitor in a background daemon thread."""
    if GPIO_AVAILABLE:
        t = threading.Thread(target=reset_button_loop, daemon=True)
        t.start()
        return t
    return None
