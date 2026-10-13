"""
messages.py - Every spoken alert in English, Tamil and Hindi.

The voice plays a recorded clip if one exists:
    voices/<language>/<message_id>.wav   (or .mp3 / .ogg)
otherwise it uses text-to-speech with the text below.

Default Tamil and Hindi clips (computer voice) are included. For a much
nicer demo, record them in your own voice:  python record_voice.py --lang ta
"""

LANGUAGES = {"en": "English", "ta": "Tamil", "hi": "Hindi"}

MESSAGES = {
    "wake_up": {
        "en": "Wake up! Please stay alert.",
        "ta": "விழித்துக் கொள்ளுங்கள்! கவனமாக ஓட்டுங்கள்.",
        "hi": "जागिए! कृपया सावधान रहिए।",
    },
    "tired": {
        "en": "You seem tired. Please take a break soon.",
        "ta": "நீங்கள் சோர்வாக இருப்பது போல் தெரிகிறது. விரைவில் ஓய்வு எடுங்கள்.",
        "hi": "आप थके हुए लग रहे हैं। कृपया जल्द ही आराम करें।",
    },
    "very_tired": {
        "en": "Warning. High fatigue detected. Please stop the vehicle and rest.",
        "ta": "எச்சரிக்கை! அதிக சோர்வு கண்டறியப்பட்டது. வாகனத்தை நிறுத்தி ஓய்வு எடுங்கள்.",
        "hi": "चेतावनी! बहुत अधिक थकान पाई गई है। कृपया गाड़ी रोककर आराम करें।",
    },
    "distracted": {
        "en": "Please keep your eyes on the road.",
        "ta": "சாலையில் கவனம் செலுத்துங்கள்.",
        "hi": "कृपया सड़क पर ध्यान दें।",
    },
    "long_drive": {
        "en": "You have been driving for a long time. Please take a short break.",
        "ta": "நீண்ட நேரமாக வாகனம் ஓட்டுகிறீர்கள். சிறிது ஓய்வு எடுங்கள்.",
        "hi": "आप काफी देर से गाड़ी चला रहे हैं। कृपया थोड़ा आराम करें।",
    },
    "night": {
        "en": "Night driving. The risk of drowsiness is high. Please stay alert.",
        "ta": "இரவு நேரப் பயணம். தூக்கம் வரும் அபாயம் அதிகம். கவனமாக இருங்கள்.",
        "hi": "रात का सफ़र है। नींद आने का खतरा ज़्यादा है। कृपया सावधान रहिए।",
    },
    "alcohol": {
        "en": "Alcohol detected. Please do not drive.",
        "ta": "மது கண்டறியப்பட்டது. வாகனம் ஓட்ட வேண்டாம்.",
        "hi": "शराब का पता चला है। कृपया गाड़ी न चलाएँ।",
    },
}


def text(msg_id, lang="en"):
    m = MESSAGES.get(msg_id, {})
    return m.get(lang) or m.get("en") or msg_id
