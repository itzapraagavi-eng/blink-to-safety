"""
pi_hardware.py - Raspberry Pi extras: buzzer, warning LED and an MQ-3
alcohol sensor. On a normal laptop (or if disabled in config.json) every
method simply does nothing, so the rest of the program never has to check.

Wiring (BCM pin numbers, change them in config.json):
    Buzzer (active, 5V/3.3V)  +  -> GPIO17      -  -> GND
    LED + 220 ohm resistor    +  -> GPIO27      -  -> GND
    MQ-3 alcohol module       VCC -> 5V   GND -> GND   DO -> GPIO22
      (turn the module's blue potentiometer to set when DO switches)
"""

import time


class PiHardware:
    def __init__(self, cfg):
        c = cfg["raspberry_pi"]
        self.enabled = False
        self.alcohol_available = False
        self._alc_since = None
        self._blink_on = False
        if not c.get("enabled"):
            return
        try:
            from gpiozero import LED, Buzzer, DigitalInputDevice
        except Exception as exc:
            print("[pi] gpiozero not available (%s) - hardware disabled" % exc)
            return
        try:
            self.buzzer = Buzzer(c["buzzer_pin"])
            self.led = LED(c["led_pin"])
            self.enabled = True
            if c.get("alcohol_sensor_pin") is not None:
                self.alcohol = DigitalInputDevice(c["alcohol_sensor_pin"], pull_up=None,
                                                  active_state=not c.get("alcohol_active_low", True))
                self.alcohol_available = True
            print("[pi] buzzer, LED%s ready" % (" and alcohol sensor" if self.alcohol_available else ""))
        except Exception as exc:
            print("[pi] could not set up GPIO pins:", exc)
            self.enabled = False

    def alarm(self, on):
        if not self.enabled:
            return
        if on:
            # beep pattern made by the buzzer itself (non-blocking)
            if not self._blink_on:
                self.buzzer.beep(on_time=0.2, off_time=0.1)
                self.led.blink(on_time=0.15, off_time=0.15)
                self._blink_on = True
        elif self._blink_on:
            self.buzzer.off()
            self.led.off()
            self._blink_on = False

    def beep(self):
        """One short beep (distraction warning)."""
        if self.enabled and not self._blink_on:
            self.buzzer.beep(on_time=0.12, off_time=0.1, n=1)

    def warning_light(self, level):
        """LED steady on for level 1-2 tiredness, off when alert."""
        if not self.enabled or self._blink_on:
            return
        if level >= 1:
            self.led.on()
        else:
            self.led.off()

    def alcohol_detected(self, hold_seconds=2.0):
        """True when the sensor has reported alcohol for hold_seconds
        (ignores single noisy readings)."""
        if not self.alcohol_available:
            return False
        now = time.monotonic()
        if self.alcohol.is_active:
            if self._alc_since is None:
                self._alc_since = now
            return now - self._alc_since >= hold_seconds
        self._alc_since = None
        return False

    def close(self):
        if self.enabled:
            self.buzzer.off()
            self.led.off()
