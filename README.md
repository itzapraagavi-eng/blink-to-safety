# Blink to Safety
### Preventing Road Accidents Using AI-Based Fatigue Detection

A real-time, multi-factor driver fatigue monitoring system. A normal webcam
watches the driver's **eyes, mouth and head**, calculates a live **fatigue score**,
and warns the driver in two levels: a gentle voice warning when they look tired,
and a loud alarm when they start falling asleep.

---

## 1. Features

| # | Feature | How it works |
|---|---|---|
| 1 | **Eye closure / blink detection** | Eye Aspect Ratio (EAR) from 6 landmarks per eye, calibrated for each driver |
| 2 | **Yawn detection** | Mouth Aspect Ratio (MAR): mouth wide open for more than 1 s (talking is ignored). Eyes squeezed shut during a yawn get 2 s extra, so yawning alone never sounds the alarm |
| 3 | **Head nod and head-drop detection** | Head pose (pitch) with OpenCV solvePnP; a short dip is a nod, staying down for 2 s raises the alarm |
| 4 | **Fatigue score (0-100)** | PERCLOS, slow blinks, yawns, nods and alarms combined into one live meter |
| 5 | **Two-level alerts** | Level 1: chime and "please take a break". Level 2: loud alarm and "Wake up!" |
| 6 | **Voice alerts** | Offline text-to-speech (pyttsx3) |
| 7 | **Trip report** | One-page report image and event list saved after every drive |
| 8 | **Emergency message** | Telegram message with a photo to a family member or fleet owner after repeated alarms |
| 9 | **Low-light mode** | Gamma correction plus CLAHE to brighten dark frames automatically |
| 10 | **CNN eye-state model** | Your own trained neural network, compared with EAR (`--method cnn / hybrid`) |
| 11 | **Raspberry Pi in-car unit** | Buzzer, warning LED, MQ-3 alcohol sensor, headless auto-start |
| 12 | **Distraction detection** | Head turned away more than 30 degrees for 2 s, or face out of view for 3 s, triggers "Eyes on the road!" Quick mirror checks are ignored |
| 13 | **Tamil / Hindi / English voice** | Every alert in 3 languages; record them in your own voice with `record_voice.py` |
| 14 | **Drive-time and night risk** | Break reminder after 2 hours (timer resets after a 10-minute break). Between 00:00 and 06:00 the system is more sensitive |
| 15 | **GPS location** | GPS module (NEO-6M / USB), approximate internet location, or a demo route. A map link and location pin go in emergency messages; distance and speed go in the trip report |
| 16 | **Fleet owner dashboard** | Live web page for the fleet owner (laptop or phone): all vehicles on a map, live alerts with sound, each driver's fatigue history and trip reports |

---

## 2. Project files

| File | What it does |
|---|---|
| `main.py` | **The live app.** Run this for the demo |
| `detector.py` | Face landmarks (MediaPipe), EAR, eye-closure timer, calibration |
| `features.py` | Mouth ratio (MAR), head pose (solvePnP), eye crops, low-light enhancement |
| `monitor.py` | Combines everything into the fatigue score and alert level |
| `alerts.py` | Decides which alert to give (chime, voice, alarm, emergency) |
| `alarm.py` / `voice.py` | Alarm sounds / spoken messages |
| `messages.py` | All voice messages in English, Tamil and Hindi |
| `voices/ta`, `voices/hi` | Default Tamil / Hindi voice clips (replace with your own) |
| `record_voice.py` | Record the alerts in your own voice |
| `drive_context.py` | Drive-time break reminders and night-risk hours |
| `gps.py` | Location from a GPS module, the internet, a fixed point or a demo route |
| `fleet_server.py` | Fleet server and dashboard (runs on the fleet owner's computer) |
| `fleet_client.py` | Sends this vehicle's status and alerts to the fleet server |
| `fleet_sim.py` | Extra simulated vehicles for demonstrating the dashboard |
| `dashboard/` | The dashboard web page (map library and fonts included, works offline) |
| `emergency.py` | Telegram emergency alert (plus its setup helper) |
| `trip_report.py` | End-of-trip report |
| `ui.py` | Everything drawn on the screen |
| `eye_cnn.py` | Runs the trained CNN model |
| `collect_eyes.py` / `train_cnn.py` | Record eye images / train the CNN |
| `evaluate.py` / `report.py` | **Accuracy test** and the numbers and charts for your paper |
| `plot_session.py` | EAR-vs-time graph for the paper |
| `pi_hardware.py` | Raspberry Pi buzzer, LED, alcohol sensor |
| `config.json` | All settings (thresholds, voice, Telegram, Pi pins) |
| `RASPBERRY_PI.md` | Wiring and setup guide for the in-car Pi unit |

Folders created automatically: `models/`, `sounds/`, `logs/`, `results/`, `data/`.

---

## 3. Setup (one time)

1. Install **Python 3.11 or newer** (3.11 to 3.14 all work) from https://www.python.org/downloads/.
   On Windows, tick **"Add Python to PATH"**.
2. Open a terminal **inside the project folder**, the one that contains `main.py` and `requirements.txt`.
   Windows "Extract All" often creates a folder inside a folder (`blink-to-safety\blink-to-safety`), so go
   into the inner one: `cd blink-to-safety`. Type `dir` and check that you can see `requirements.txt`.
3. Install the libraries:
   ```
   pip install -r requirements.txt
   ```
4. Run it:
   ```
   python main.py
   ```
   The first run downloads the face model (~3.6 MB), so stay online.

---

## 4. Using the live app

1. Look at the screen with your eyes open for **3 seconds** (calibration). The system learns
   *your* normal eye opening and head angle.
2. Drive normally: blinking, talking and checking mirrors give no alarm.
3. Yawning, nodding and slow blinks raise the **FATIGUE** meter on the right.
   At 35 you hear a chime and *"You seem tired. Please take a break soon."*
4. Eyes closed for 1.5 s, or the head dropped for 2 s with the eyes closed, triggers a **red alert**, the loud
   alarm and *"Wake up!"* (Head down with the eyes **open** means looking down at a phone, so it gives the
   purple distraction warning instead.)
   Looking away from the road for 2 s triggers a **purple "EYES ON THE ROAD!"** warning.
5. Press **q** to quit. The trip report is saved in `results/`.

**Keys:** `q` quit, `c` recalibrate (new driver), `m` mute alarm, `v` voice on/off

**Screen guide:**
- Top-left panel: EAR, MAR (mouth), head angle, status, blink/yawn/nod/alarm counts, PERCLOS.
- The bar under the panel fills while the eyes are closed. When it is full, the alarm sounds.
- The right meter shows the fatigue score (green: alert, amber: tired, red: very tired).
- Tags at the top appear when **YAWNING** or **HEAD DOWN** is detected.

**Options:**
```
python main.py --method cnn        # use your trained CNN for open/closed eyes
python main.py --method hybrid     # EAR + CNN together (most reliable)
python main.py --camera 1          # USB webcam
python main.py --video demo.mp4    # recorded video (demo-day backup)
python main.py --seconds 2.0       # eyes-closed time before alarm
python main.py --no-voice --mute   # silent testing
python main.py --lang ta           # Tamil voice alerts (hi = Hindi, en = English)
python main.py --clock 02:30 --driven 2   # demo: 2:30 AM, already driven 2 hours
```
The `--clock` and `--driven` options are only for demonstrating the night-risk and
break-reminder features during the day. Normally the real clock is used.

---

## 5. How it works (for your paper and viva)

**Eye Aspect Ratio (EAR)**
```
       |p2 - p6| + |p3 - p5|        p1, p4 = eye corners
EAR = -----------------------       p2, p3 = upper lid, p5, p6 = lower lid
            2 x |p1 - p4|
```
Open eye: about 0.25-0.35. Closed eye: about 0.1-0.15. The threshold is 65% of the driver's own normal
EAR, measured during calibration and then kept up to date from the last 30 seconds (people often open
their eyes wider than usual while being calibrated; the limit can only become more relaxed, never stricter). (65% was chosen from real webcam data: 75% counted relaxed or
downward-looking eyes as closed; 60% started missing real closures.) When the head tilts down, the limit
is lowered by up to 30%, because the eyelids naturally drop when looking down.

**Mouth Aspect Ratio (MAR):** the average inner-lip opening divided by the mouth width.
Closed mouth is below 0.1, talking is 0.1-0.4, and a yawn is above 0.5. A yawn must last
more than 1 s, so talking is not counted.

**Head pose:** OpenCV `solvePnP` matches 6 face points (nose, chin, eye corners, mouth corners)
to an average 3-D face to get the head's pitch angle. "Head down" means more than 20 degrees below
the driver's normal angle.

**PERCLOS** (PERcentage of eyelid CLOSure): the percentage of time the eyes were closed in the
last 60 s. It is a widely used research measure of drowsiness.

**Fatigue score (0-100)** = PERCLOS x 250 (max 50) + 12 per yawn (max 30) + 15 per nod (max 30)
+ 5 per slow blink (max 20) + 20 per drowsy alarm (max 40), counting recent events only.

| Level | Score / trigger | Alert |
|---|---|---|
| ALERT | below 35 | none |
| TIRED | 35-64 | chime + "Please take a break soon" + LED |
| VERY TIRED | 65+ | chime + "Please stop the vehicle and rest" |
| DROWSY | eyes closed >= 1.5 s, or head down >= 2 s with eyes closed | loud alarm + "Wake up!" + buzzer |

**Emergency:** 3 drowsy alarms within 10 minutes sends a Telegram message with a photo.

**Distraction:** head pose also gives the *yaw* (left-right turn). Turning more than 30 degrees
from the driver's normal angle for more than 2 s, or the face leaving the camera view for
3 s, gives a purple **DISTRACTED** warning, a repeating chime and *"Please keep your eyes on
the road"*. Mirror checks (about 1 s) are too short to trigger it. While the head is turned
far, eye closure is not used, because the eye shape looks different from the side.

**Drive time and night risk:** sleep-related crashes are most common in the early morning
hours, when the body clock pushes us to sleep, and after long periods of driving without a break.
- After **2 hours** of driving, the system says *"please take a short break"*, then reminds you every 30 minutes.
  If the driver is away from the seat for 10 minutes, it counts as a break and the timer resets.
- Between **00:00 and 06:00**, the eye-closure limit drops from 1.5 s to **1.2 s** and the fatigue
  score gets **+10**. Driving beyond 2 hours adds +5 per hour (max 15).

**Voice languages:** all messages are in `messages.py` in English, Tamil and Hindi. The default
Tamil and Hindi clips use a computer voice, so for a better demo record them yourself:
```
pip install sounddevice
python record_voice.py --lang ta
python voice.py --lang ta          # listen to all alerts
```
No microphone? Record on your phone and save the files as `voices/ta/wake_up.mp3` and so on
(the file names are listed in `record_voice.py`).

---

## 6. Settings (`config.json`)

Open it in Notepad. The most useful settings are:

| Setting | Default | Meaning |
|---|---|---|
| `detection.method` | `"ear"` | `"ear"`, `"cnn"` or `"hybrid"` |
| `detection.closed_seconds` | 1.5 | eyes closed this long = alarm |
| `detection.ear_threshold` | null | null = auto-calibrate; or a fixed value like 0.21 |
| `yawn.mar_threshold` | 0.5 | lower = more sensitive yawn detection |
| `head.down_degrees` | 20 | head-down angle |
| `fatigue.tired_level` | 35 | score for the first warning |
| `alerts.voice` | true | spoken messages on/off |
| `alerts.language` | `"en"` | `"en"`, `"ta"` (Tamil) or `"hi"` (Hindi) |
| `head.away_degrees` / `distract_seconds` | 30 / 2.0 | looking-away angle and time |
| `drive.break_reminder_minutes` | 120 | break reminder after this long |
| `drive.risk_hours` | [[0, 6]] | high-risk hours; add [14, 16] for the afternoon dip |
| `emergency.*` | off | Telegram setup, see section 9 |
| `raspberry_pi.*` | off | Pi pins, see RASPBERRY_PI.md |
| `driver.name` / `driver.vehicle` | Driver / TN01AB1234 | shown on the dashboard and in emergency messages |
| `gps.source` | `"none"` | `"nmea"` (GPS module), `"ip"`, `"fixed"`, `"sim"` |
| `fleet.enabled` / `server` / `key` | off | fleet dashboard connection (section 11) |

---

## 7. CNN eye-state model (feature 10)

The EAR method uses geometry. The CNN *learns* what open and closed eyes look like. Comparing the
two makes a strong results section.

**Step 1: Record eye images** (about 1 minute per person and lighting):
```
python collect_eyes.py --person P1
python collect_eyes.py --person P1 --condition dim
python collect_eyes.py --person P2
```
Aim for 3 or more people. You can also add the free **MRL Eye Dataset** (about 85,000 eye images).

**Step 2: Train** (a few minutes on a laptop):
```
pip install -r requirements-cnn.txt
python train_cnn.py
python train_cnn.py --test-person P2                # fair test on a person it never saw
python train_cnn.py --mrl path/to/mrlEyes_2018_01   # include the MRL dataset
```
This saves `models/eye_cnn.onnx`, plus `results/cnn_metrics.txt`, `cnn_confusion_matrix.png` and
`cnn_training_curve.png`.

No good laptop? Use **Google Colab** (free). Upload the project zip, run
`!pip install -r requirements-cnn.txt`, then run `!python train_cnn.py`, and download `models/eye_cnn.onnx`.

**Step 3: Use it:** `python main.py --method cnn` or `--method hybrid`

The model is a 3-layer CNN (16, 32, 64 filters) with about 90,000 parameters, taking a 32x32 grey eye image.
It runs inside OpenCV, so the live app doesn't need PyTorch.

---

## 8. Getting REAL results for your paper

### a) Accuracy test (fills the numbers in your paper)
```
python evaluate.py --person P1 --condition "normal light"
```
It runs 35 guided trials (about 7 minutes) in random order. **A voice tells you what to do** before each trial ("Next. Close your eyes at the beep"), a **high double ding** starts the trial and a **low ding** ends it (with "Open your eyes"):

| Trial | You do | Correct result |
|---|---|---|
| DROWSY | close your eyes from the high ding to the low ding (4 s) | alarm |
| HEAD DROP | drop your head forward with your eyes closed, like dozing | alarm |
| AWAKE | blink, talk, smile, check mirrors or glance at the speedometer for about 1 s | **no** alarm |
| YAWN | yawn or open your mouth wide | yawn detected, **no** alarm |
| DISTRACT | look out of the side window | distraction warning, **no** drowsy alarm |

Repeat this with more people, conditions and methods. Every run is added to `results/trials.csv`:
```
python evaluate.py --person P2 --condition "normal light"
python evaluate.py --person P1 --condition "dim light"
python evaluate.py --person P1 --condition "normal light" --method cnn
python evaluate.py --quick          # only eyes trials (3 min)
```
The `results/` folder then contains:
- `summary.txt`: accuracy, precision, recall, specificity, **false-alarm rate**, F1, alert time,
  yawn detection rate, head-drop detection, distraction detection, and false alarms per activity
- `confusion_matrix_EAR.png` (one per method)
- `method_comparison.png`: EAR vs CNN vs Hybrid
- `accuracy_by_condition.png`: for example, normal vs dim vs glasses
- `no_false_alarm_by_activity.png`: proof that talking or checking mirrors does not trigger it

### b) Figures from a drive
After any `main.py` session:
- `results/trip_report_*.png`: the fatigue timeline with yawns, nods and alarms marked
- `python plot_session.py`: EAR vs time graph

---

## 9. Emergency Telegram alert (free)

1. In Telegram, open **@BotFather**, send `/newbot`, and copy the **token**.
2. The person receiving alerts opens your bot and presses **Start**.
3. Paste the token into `config.json` under `emergency` > `telegram_bot_token`, then run:
   ```
   python emergency.py --get-chat-id
   ```
4. Copy the number into `telegram_chat_id` and set `"enabled": true`.
5. Test it with `python emergency.py --test`.

---

## 10. Raspberry Pi in-car unit

See **RASPBERRY_PI.md** for parts, wiring, setup and auto-start. Quick run:
```
python main.py --pi --width 480 --height 360
```

---

## 11. GPS location and fleet owner dashboard

### GPS location
| Source | Use it for | How |
|---|---|---|
| `nmea` | Real position and speed | GPS module (NEO-6M on the Pi, or a USB GPS dongle on the laptop). `pip install pyserial`, then `python main.py --gps nmea` |
| `ip` | Approximate city-level position | Needs internet only: `python main.py --gps ip` |
| `fixed` | A fixed place, like the college | Set `fixed_lat` / `fixed_lon` in `config.json` |
| `sim` | Demo only | Drives along a real highway (Chennai to Vellore by default). Marked "SIM" everywhere |

Test a GPS module on its own with `python gps.py --source nmea` (go near a window; the first fix
can take 1-5 minutes outdoors). With GPS on:
- the emergency Telegram message includes a **Google Maps link, the speed, and a location pin**;
- the trip report shows the **distance driven, average speed and top speed**;
- the fleet dashboard shows the vehicle on the **map**.

### Fleet owner dashboard
For bus, truck and taxi companies: one screen shows every vehicle and warns the owner the moment a driver falls asleep.

**1. Start the server** on the fleet owner's computer:
```
python fleet_server.py --key mysecret
```
It prints two addresses: one for this computer, and one for a phone on the same Wi-Fi.

**2. Connect each vehicle:**
```
python main.py --fleet http://SERVER-ADDRESS:8000 --key mysecret --driver "Ravi" --vehicle TN01AB1234 --gps nmea
```
For a demo on one laptop, use `--fleet http://localhost:8000 --gps sim`.

**3. Open the dashboard** in a browser and enter the key. You'll see:
- **Vehicles:** each vehicle as a yellow number plate with the driver's status (alert, tired, very tired,
  falling asleep, eyes off the road, offline), fatigue score, speed and driving time;
- **Map:** live positions (the map background needs internet; the rest works offline). Click a vehicle to see its route;
- **Live alerts:** drowsiness alarms, eyes off the road, warnings, emergencies, with a link to the location;
- **A red banner and alarm sound** when any driver is falling asleep, with a button to show them on the map;
- **Vehicle details:** fatigue chart (last 60 minutes), today's counts, recent alerts, and trip reports
  (uploaded automatically when the driver quits the app).

**4. Optional: extra demo vehicles.** One laptop is only one vehicle. To show what a fleet looks like:
```
python fleet_sim.py --key mysecret
```
This adds 4 simulated vehicles on Tamil Nadu highways. They are labelled **Simulated** on the dashboard,
so always say clearly that they are simulated.

**How it works:** the app sends a small status message every 2 seconds and each alert immediately.
This happens in the background, so a slow network never freezes the camera. If the connection drops,
alerts are kept and sent when it comes back. The server stores everything in `fleet_data/fleet.db`
(SQLite) and only uses Python's built-in libraries. Everything needs the access key.

**Real deployment:** the server would run on a cloud machine with HTTPS, and each vehicle would connect
over a mobile data SIM (for example a 4G dongle on the Raspberry Pi). For the project demo, a laptop on Wi-Fi is enough.

---

## 12. Drowsy vs drunk: what this system detects

This system detects **drowsiness** (sleepiness / fatigue), **not alcohol**.
- A driver who is **alert** (not sleepy) will **not** be detected. Blinking, talking, smiling and
  checking mirrors don't trigger it, and `evaluate.py` measures this as the false-alarm rate.
- A **drunk but wide-awake** driver will also **not** be detected from the camera, because their eyes stay open.
  A drunk driver who becomes **sleepy** *will* be detected, because the eyes and head show it.
- Alcohol detection is only possible with the optional **MQ-3 alcohol sensor** on the Raspberry Pi unit.
  It is a screening indicator, not a certified breathalyser.

---

## 13. Limitations and future work (say these honestly)

**Limitations:** very dark cabins need an IR camera, sunglasses hide the eyes, extreme head
turns (more than 45 degrees) lose the face, and the fatigue score weights are chosen by design, not learned.

**Future work:** an IR/NoIR camera for night driving, learning the fatigue weights from real driving data,
phone-use detection with object detection (YOLO), HTTPS cloud hosting and driver logins for the fleet
dashboard, SMS alerts where there is no internet, and a vehicle CAN-bus link.

---

## 14. Demo-day tips

- Light should fall **on your face**, not from behind. Keep the laptop at eye level, 50-70 cm away.
- Calibrate with the presenter (press **c** when someone new sits down).
- Show in this order: **blink** (nothing happens), **talk / look at mirror** (nothing), **yawn**
  (YAWNING tag, meter rises), **nod**, **look out of the window for 3 s** (EYES ON THE ROAD),
  then **close your eyes** (alarm). Quit to show the **trip report**.
- Run with `--lang ta --clock 02:30 --driven 2` to show the Tamil voice, night mode and the
  break reminder in one go.
- Turn the volume up. Test voice with `python voice.py`.
- Backup: record your demo and play it with `python main.py --video demo.mp4`.
- Fleet demo: start `fleet_server.py` and `fleet_sim.py` first, open the dashboard on a second screen or
  your phone, then run `main.py --fleet http://localhost:8000 --gps sim`. When you close your eyes, the
  dashboard turns red and beeps at the same moment.

---

## 15. Troubleshooting

| Problem | Fix |
|---|---|
| "Could not open requirements file" | You are one folder too high. Run `cd blink-to-safety` and try again |
| `pip install` fails for mediapipe | Check `python --version` is 3.11 or newer; update pip: `python -m pip install --upgrade pip` |
| "Could not open webcam 0" | Close Zoom/Meet/Camera app; try `--camera 1` |
| Model download fails | Download the link shown in the error to `models/face_landmarker.task` |
| False alarms with open eyes | Press **c** to recalibrate in good light, or use `--threshold 0.18` |
| Alarm doesn't trigger | Better light on your face; try `--threshold 0.25` |
| Yawns not detected | Lower `yawn.mar_threshold` to 0.4 in `config.json` |
| Head drop too sensitive | Raise `head.down_degrees` to 25 |
| No voice | Run `python voice.py`; check the volume; `pip install pyttsx3` |
| Tamil/Hindi sounds robotic | Record your own clips: `python record_voice.py --lang ta` |
| Distraction alert too sensitive | Raise `head.away_degrees` to 35 or `distract_seconds` to 2.5 |
| GPS shows "no module" | Check the port (`port` in config.json, e.g. `COM5`); on the Pi enable the serial port in `raspi-config` |
| GPS stuck on "searching" | A GPS needs to see the sky: go outdoors or near a window and wait a few minutes |
| Dashboard shows "Server not reachable" | Is `fleet_server.py` still running? Same Wi-Fi? Allow Python through the Windows firewall |
| Vehicle shows FLEET in red | Wrong `--fleet` address or key; the server must be started first |
| Map is grey | The map background needs internet; positions and alerts still work |
| "CNN model not found" | Train it first (section 7) or use `--method ear` |
| Slow / low FPS | Close other apps; plug in the charger; use `--width 480 --height 360` |
