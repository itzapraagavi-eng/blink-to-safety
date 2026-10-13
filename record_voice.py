"""
record_voice.py - Record the voice alerts in your own voice (any language).
A human voice in Tamil or Hindi sounds far better than a computer voice and
makes a great demo.

    pip install sounddevice
    python record_voice.py --lang ta          (Tamil)
    python record_voice.py --lang hi          (Hindi)
    python record_voice.py --lang en          (English, optional)
    python record_voice.py --lang ta --only wake_up

For each message: read the text shown, press Enter, speak after the beep.
Recording stops by itself. Then press Enter to keep it or r to record again.

No microphone on the laptop? Record on your phone instead, save the files as
    voices/<lang>/wake_up.mp3, tired.mp3, very_tired.mp3, distracted.mp3,
    long_drive.mp3, night.mp3, alcohol.mp3
and copy them into the project folder. .wav, .mp3 and .ogg all work.
"""

import argparse
import os
import sys
import wave

import numpy as np

from messages import LANGUAGES, MESSAGES, text
from voice import VOICE_DIR

RATE = 22050


def trim(audio, threshold=0.02, pad=0.15):
    """Remove silence at the start and end."""
    loud = np.where(np.abs(audio) > threshold)[0]
    if len(loud) == 0:
        return audio
    a = max(0, loud[0] - int(pad * RATE))
    b = min(len(audio), loud[-1] + int(pad * RATE))
    return audio[a:b]


def save_wav(path, audio):
    peak = np.max(np.abs(audio)) or 1.0
    audio = audio / peak * 0.9                      # normalise volume
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())


def main():
    try:   # show Tamil / Hindi text even in an old Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Record voice alerts in your own voice")
    p.add_argument("--lang", default="ta", choices=list(LANGUAGES))
    p.add_argument("--only", default=None, help="record just one message id")
    args = p.parse_args()
    try:
        import sounddevice as sd
    except ImportError:
        raise SystemExit("Install the recorder first:  pip install sounddevice")

    ids = [args.only] if args.only else list(MESSAGES)
    print("Recording %s alerts. Speak clearly, a little loud, like a warning.\n" % LANGUAGES[args.lang])
    for mid in ids:
        if mid not in MESSAGES:
            print("Unknown message id:", mid)
            continue
        words = text(mid, args.lang)
        seconds = max(3.0, len(text(mid, "en").split()) * 0.55 + 1.5)
        while True:
            print("[%s]  %s" % (mid, words))
            if args.lang != "en":
                print("        (meaning: %s)" % text(mid, "en"))
            input("   Press Enter, then speak after the beep (%.0f s)..." % seconds)
            beep = 0.3 * np.sin(2 * np.pi * 880 * np.arange(int(0.15 * RATE)) / RATE)
            sd.play(beep.astype(np.float32), RATE); sd.wait()
            audio = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="float32")
            sd.wait()
            audio = trim(audio[:, 0])
            print("   Playing back...")
            sd.play(audio, RATE); sd.wait()
            ans = input("   Enter = keep,  r = record again,  s = skip: ").strip().lower()
            if ans == "r":
                continue
            if ans != "s":
                path = os.path.join(VOICE_DIR, args.lang, mid + ".wav")
                # remove older clips with other extensions so the new one is used
                for ext in (".mp3", ".ogg"):
                    old = os.path.join(VOICE_DIR, args.lang, mid + ext)
                    if os.path.exists(old):
                        os.remove(old)
                save_wav(path, audio)
                print("   Saved", path)
            print()
            break
    print("Done. Use it:  python main.py --lang %s" % args.lang)


if __name__ == "__main__":
    main()
