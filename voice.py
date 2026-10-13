"""
voice.py - Spoken alerts in English, Tamil or Hindi. Speech runs in a
background thread so the video never freezes.

For each message it tries, in order:
  1. a recorded clip  voices/<lang>/<message_id>.wav|.mp3|.ogg   (best quality)
  2. pyttsx3 text-to-speech with a voice of that language, if installed
  3. Windows speech (PowerShell) / espeak on Linux and Raspberry Pi
  4. English text-to-speech, and finally just printing the message

Test it:   python voice.py --lang ta
"""

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

from messages import LANGUAGES, MESSAGES, text

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.join(PROJECT_DIR, "voices")
VOICE_HINTS = {   # words found in the names of installed voices
    "ta": ("tamil", "valluvar", "ta-in", "ta_in"),
    "hi": ("hindi", "kalpana", "hemant", "hi-in", "hi_in"),
    "en": ("english", "en-us", "en_us", "en-gb", "en-in", "zira", "david"),
}


def clip_path(msg_id, lang):
    for ext in (".wav", ".mp3", ".ogg"):
        p = os.path.join(VOICE_DIR, lang, msg_id + ext)
        if os.path.exists(p):
            return p
    return None


class Voice:
    def __init__(self, enabled=True, rate=165, lang="en"):
        self.enabled = enabled
        self.rate = rate
        self.lang = lang if lang in LANGUAGES else "en"
        self._q = queue.Queue()
        self._interrupt = threading.Event()
        self._speaking_urgent = False
        self._warned = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def say(self, msg_id, urgent=False):
        """msg_id: a key of messages.MESSAGES, e.g. 'wake_up'.
        urgent=True (wake up / eyes on the road) skips everything waiting and
        cuts off a less important message that is playing right now."""
        if not self.enabled:
            return
        if urgent:
            while True:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            if not self._speaking_urgent:
                self._interrupt.set()
            self._q.put((msg_id, True))
            return
        while self._q.qsize() > 1:      # keep only the newest if speech falls behind
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._q.put((msg_id, False))

    def close(self):
        self._q.put(None)

    # ------------------------------------------------------------------
    def _worker(self):
        try:
            import pyttsx3
        except Exception:
            pyttsx3 = None
        while True:
            item = self._q.get()
            if item is None:
                return
            msg_id, urgent = item
            self._interrupt.clear()
            self._speaking_urgent = urgent
            clip = clip_path(msg_id, self.lang)
            if clip and self._play_clip(clip):
                continue
            words = text(msg_id, self.lang)
            if pyttsx3 is not None and self._speak_pyttsx3(pyttsx3, words, self.lang):
                continue
            if self._speak_system(words, self.lang):
                continue
            if self.lang != "en":
                if not self._warned:
                    print("[voice] no %s voice found - using English. Record clips with: "
                          "python record_voice.py --lang %s" % (LANGUAGES[self.lang], self.lang))
                    self._warned = True
                eng = text(msg_id, "en")
                if pyttsx3 is not None and self._speak_pyttsx3(pyttsx3, eng, "en"):
                    continue
                if self._speak_system(eng, "en"):
                    continue
            print("[voice] " + text(msg_id, "en"))

    def _play_clip(self, path):
        try:
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            snd = pygame.mixer.Sound(path)
            channel = snd.play()
            end = time.monotonic() + snd.get_length() + 0.1
            while time.monotonic() < end:          # stop early for an urgent message
                if self._interrupt.is_set():
                    if channel is not None:
                        channel.stop()
                    break
                time.sleep(0.03)
            return True
        except Exception:
            if sys.platform.startswith("win") and path.endswith(".wav"):
                try:
                    import winsound
                    winsound.PlaySound(path, winsound.SND_FILENAME)
                    return True
                except Exception:
                    pass
            return False

    def _speak_pyttsx3(self, pyttsx3, words, lang):
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            if lang != "en":
                chosen = None
                for v in engine.getProperty("voices"):
                    desc = (str(v.id) + " " + str(v.name) + " " +
                            " ".join(str(x) for x in (v.languages or []))).lower()
                    if any(h in desc for h in VOICE_HINTS[lang]):
                        chosen = v.id
                        break
                if chosen is None:
                    return False
                engine.setProperty("voice", chosen)
            engine.say(words)
            engine.runAndWait()
            engine.stop()
            return True
        except Exception:
            return False

    def _speak_system(self, words, lang):
        try:
            if sys.platform.startswith("win"):
                if lang != "en":
                    return False      # Windows needs a language pack; use clips instead
                safe = words.replace("'", "").replace('"', "")
                cmd = ("Add-Type -AssemblyName System.Speech; "
                       "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('%s')" % safe)
                subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                               timeout=20, creationflags=0x08000000)   # no console window
                return True
            for exe in ("espeak-ng", "espeak"):
                if shutil.which(exe):
                    subprocess.run([exe, "-v", lang, "-s", str(self.rate), words], timeout=20,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
            if sys.platform == "darwin" and lang == "en":
                subprocess.run(["say", words], timeout=20)
                return True
        except Exception:
            pass
        return False


if __name__ == "__main__":
    try:   # show Tamil / Hindi text even in an old Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Play every voice alert")
    ap.add_argument("--lang", default="en", choices=list(LANGUAGES))
    a = ap.parse_args()
    v = Voice(lang=a.lang)
    for mid in MESSAGES:
        print("%-11s %s" % (mid, text(mid, a.lang)))
        v.say(mid)
        time.sleep(5.5)
