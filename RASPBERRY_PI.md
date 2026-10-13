# Blink to Safety on a Raspberry Pi (in-car unit)

This turns the project into a small box that sits on the dashboard, with no laptop needed.

## 1. Parts

| Part | Notes | Approx. cost |
|---|---|---|
| Raspberry Pi 4 (4 GB) or Pi 5 | Pi 5 is faster | Rs 5,000 - 8,000 |
| USB webcam **or** Pi Camera Module 3 | For night use: a *NoIR* camera + IR LEDs | Rs 1,000 - 3,000 |
| microSD card, 32 GB | Raspberry Pi OS 64-bit (Bookworm) | Rs 400 |
| Active buzzer (3.3-5 V) | Loud alarm | Rs 30 |
| LED + 220 ohm resistor | Warning light | Rs 10 |
| MQ-3 alcohol sensor module (optional) | The digital-output (DO) type | Rs 150 |
| NEO-6M GPS module with antenna (optional) | For location and speed | Rs 400 - 600 |
| 4G USB dongle with a data SIM (optional) | Internet for the fleet dashboard and Telegram | Rs 1,500 |
| Car USB charger, 5 V 3 A + cable | Power from the car | Rs 400 |
| Small speaker (3.5 mm or USB) | For voice alerts (optional) | Rs 300 |

## 2. Wiring (BCM pin numbers)

| From | To Raspberry Pi |
|---|---|
| Buzzer **+** | GPIO 17 (pin 11) |
| Buzzer **-** | GND (pin 9) |
| LED **+** (long leg) via 220 ohm resistor | GPIO 27 (pin 13) |
| LED **-** | GND (pin 14) |
| MQ-3 **VCC** | 5 V (pin 2) |
| MQ-3 **GND** | GND (pin 6) |
| MQ-3 **DO** | GPIO 22 (pin 15) |
| GPS **VCC** | 3.3 V (pin 1) |
| GPS **GND** | GND (pin 20) |
| GPS **TX** | GPIO 15 / RXD (pin 10) |
| GPS **RX** | GPIO 14 / TXD (pin 8) |

For the GPS: run `sudo raspi-config`, then Interface Options, then Serial Port. Answer **No** to
"login shell over serial" and **Yes** to "serial port hardware", then reboot.
Test with `python gps.py --source nmea`. The antenna must see the sky; on the dashboard under
the windscreen is best.

Different pins? Change them in `config.json` under `"raspberry_pi"`.

**Important (MQ-3):** most modules give 5 V on DO when powered from 5 V. Pi pins are
**3.3 V only**. Put a simple voltage divider on DO (10 kohm from DO to GPIO 22, and
20 kohm from GPIO 22 to GND), or power the module from 3.3 V if your module supports it.

## 3. Software setup

```bash
sudo apt update
sudo apt install -y python3-venv espeak python3-picamera2
cd ~/blink-to-safety
python3 -m venv --system-site-packages env      # keeps picamera2 + gpiozero
source env/bin/activate
pip install -r requirements.txt
```

## 4. Run

```bash
# USB webcam, smaller frames for speed
python main.py --pi --width 480 --height 360

# Pi Camera Module
python main.py --pi --picam --width 480 --height 360

# No screen (box in the car): sound, buzzer, LED and Telegram only
python main.py --pi --headless

# Full in-car unit: GPS + fleet dashboard
python main.py --pi --headless --gps nmea --fleet http://SERVER:8000 --key KEY --driver "Ravi" --vehicle TN01AB1234
```

The FPS is shown on screen. If it is below about 10, use `--width 320 --height 240`.

## 5. Start automatically when the car starts

Create `/etc/systemd/system/blink.service`:

```ini
[Unit]
Description=Blink to Safety driver monitor
After=multi-user.target

[Service]
User=pi
WorkingDirectory=/home/pi/blink-to-safety
ExecStart=/home/pi/blink-to-safety/env/bin/python main.py --pi --headless --width 480 --height 360
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl enable blink.service
sudo systemctl start blink.service
```

Change `pi` to your username if it is different.

## 6. About the alcohol sensor (read before presenting)

- The MQ-3 needs **1-2 minutes to warm up** every time it is powered on, and works best
  after about 24 hours of first-time "burn-in".
- Turn the blue knob on the module to set when DO switches on. Test it with a cotton
  ball dipped in hand sanitiser (it contains alcohol) held near the sensor.
- It is a **screening indicator, not a certified breathalyser.** It shows that alcohol
  vapour is present near the driver. It cannot measure blood alcohol level. Say this
  clearly to the judges.
- Place it near the steering wheel, where the driver's breath reaches it.
