"""
emergency.py - Sends an emergency message (and a photo) to a family member
or fleet owner through Telegram when the driver keeps falling asleep.

Free to use, no SMS charges. One-time setup (5 minutes):
  1. In Telegram, open @BotFather, send /newbot, follow the steps.
     Copy the bot token it gives you (looks like 123456:ABC-DEF...).
  2. The person who should receive alerts opens your new bot and presses
     Start (or sends it any message).
  3. Put the token in config.json -> "emergency" -> "telegram_bot_token", then run:
         python emergency.py --get-chat-id
     Copy the number it prints into "telegram_chat_id" and set "enabled": true.
  4. Test it:
         python emergency.py --test
"""

import argparse
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid
from collections import deque
from datetime import datetime

import cv2

from config import load_config
from gps import maps_link

API = "https://api.telegram.org/bot%s/%s"


def _post(token, method, fields, photo_bytes=None, timeout=15):
    url = API % (token, method)
    if photo_bytes is None:
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(url, data=data)
    else:   # multipart/form-data upload for the photo
        boundary = uuid.uuid4().hex
        body = bytearray()
        for k, v in fields.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v)).encode()
        body += ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; "
                 "filename=\"driver.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n" % boundary).encode()
        body += photo_bytes + b"\r\n" + ("--%s--\r\n" % boundary).encode()
        req = urllib.request.Request(url, data=bytes(body))
        req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class EmergencyAlert:
    def __init__(self, cfg):
        e = cfg["emergency"]
        self.cfg = e
        self.driver = cfg.get("driver", {})
        self.enabled = bool(e["enabled"] and e["telegram_bot_token"] and e["telegram_chat_id"])
        self.alarm_times = deque()
        self.last_sent = {}
        self.sent_count = 0

    def _send_async(self, text, frame=None, location=None):
        def job():
            try:
                photo = None
                if frame is not None and self.cfg.get("send_photo", True):
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    photo = buf.tobytes() if ok else None
                fields = {"chat_id": self.cfg["telegram_chat_id"]}
                if photo:
                    fields["caption"] = text
                    _post(self.cfg["telegram_bot_token"], "sendPhoto", fields, photo)
                else:
                    fields["text"] = text
                    _post(self.cfg["telegram_bot_token"], "sendMessage", fields)
                if location and self.cfg.get("send_location", True):
                    # a location pin the family member can tap to open in maps
                    _post(self.cfg["telegram_bot_token"], "sendLocation",
                          {"chat_id": self.cfg["telegram_chat_id"],
                           "latitude": "%.6f" % location["lat"],
                           "longitude": "%.6f" % location["lon"]})
                self.sent_count += 1
                print("[emergency] alert sent")
            except Exception as exc:
                print("[emergency] could not send alert:", exc)
        threading.Thread(target=job, daemon=True).start()

    def _header(self):
        who = self.driver.get("name") or "Driver"
        veh = self.driver.get("vehicle")
        return "%s%s" % (who, (" (" + veh + ")") if veh else "")

    @staticmethod
    def _where(location):
        if not location:
            return ""
        txt = "\nLocation: %s" % maps_link(location["lat"], location["lon"])
        if location.get("source") == "ip":
            txt += " (approximate)"
        elif location.get("source") == "sim":
            txt += " (SIMULATED demo location)"
        if location.get("speed_kmh") is not None:
            txt += "\nSpeed: %d km/h" % round(location["speed_kmh"])
        return txt

    def record_alarm(self, now, frame=None, fatigue=None, location=None):
        """Call once per drowsy alarm. Sends a message when too many happen
        close together. Returns True if a message was sent."""
        if not self.enabled:
            return False
        window = self.cfg["window_minutes"] * 60
        self.alarm_times.append(now)
        while self.alarm_times and now - self.alarm_times[0] > window:
            self.alarm_times.popleft()
        if len(self.alarm_times) < self.cfg["alarms_before_alert"]:
            return False
        if now - self.last_sent.get("drowsy", -1e9) < window:
            return False                       # don't spam: one message per window
        self.last_sent["drowsy"] = now
        text = ("EMERGENCY - Blink to Safety\n"
                "%s fell asleep %d times in the last %d minutes.\n"
                "Time: %s%s%s\nPlease call the driver now and ask them to stop and rest."
                % (self._header(), len(self.alarm_times), self.cfg["window_minutes"],
                   datetime.now().strftime("%d %b %Y, %I:%M %p"),
                   ("\nFatigue score: %d/100" % fatigue) if fatigue is not None else "",
                   self._where(location)))
        self._send_async(text, frame, location)
        return True

    def alcohol_alert(self, now, frame=None, location=None):
        if not self.enabled or now - self.last_sent.get("alcohol", -1e9) < 600:
            return False
        self.last_sent["alcohol"] = now
        text = ("WARNING - Blink to Safety\nAlcohol detected in %s's vehicle.\nTime: %s%s"
                % (self._header(), datetime.now().strftime("%d %b %Y, %I:%M %p"),
                   self._where(location)))
        self._send_async(text, frame, location)
        return True


def main():
    p = argparse.ArgumentParser(description="Telegram emergency alert setup")
    p.add_argument("--get-chat-id", action="store_true", help="show chat ids that messaged your bot")
    p.add_argument("--test", action="store_true", help="send a test message")
    args = p.parse_args()
    cfg = load_config()["emergency"]
    token = cfg["telegram_bot_token"]
    if not token:
        raise SystemExit("First put your bot token in config.json -> emergency -> telegram_bot_token")
    if args.get_chat_id:
        res = _post(token, "getUpdates", {})
        chats = {}
        for upd in res.get("result", []):
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat")
            if chat:
                chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
        if not chats:
            print("No messages yet. Open your bot in Telegram, press Start, then run this again.")
        for cid, name in chats.items():
            print("chat id: %s   (%s)" % (cid, name))
    elif args.test:
        if not cfg["telegram_chat_id"]:
            raise SystemExit("Set telegram_chat_id in config.json first (use --get-chat-id)")
        res = _post(token, "sendMessage", {"chat_id": cfg["telegram_chat_id"],
                                           "text": "Blink to Safety: test alert. Setup works!"})
        print("Sent!" if res.get("ok") else res)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
