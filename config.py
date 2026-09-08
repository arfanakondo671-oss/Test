import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# Comma-separated Telegram user IDs
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "123456789").split(",")
    if x.strip().isdigit()
}

START_POINTS = int(os.getenv("START_POINTS", "3"))
DAILY_BONUS = int(os.getenv("DAILY_BONUS", "3"))
CALL_COST = int(os.getenv("CALL_COST", "1"))
REFERRAL_REWARD = int(os.getenv("REFERRAL_REWARD", "1"))

PRANK_API = "http://arfan.0web.top/prank.php"
HISTORY_API = "http://arfan.0web.top/history.php"

CHANNELS = [
    {
        "name": "📢  Main Channel",
        "link": "https://t.me/+j5OMnGqNqBMzZjM1",
        "id": -1002306511083,
        "key": "ch1",
    },
    {
        "name": "📥  2nd Channel",
        "link": "https://t.me/ModiFyXdownload",
        "id": -1003116790456,
        "key": "ch2",
    },
    {
        "name": "🔐  3rd Channel",
        "link": "https://t.me/+yE9uJ1Wtkc40NDA1",
        "id": -1003844155880,
        "key": "ch3",
    },
    {
        "name": "⭐  4th Channel",
        "link": "https://t.me/+0hGCY2z0JK80NDg1",
        "id": -1002503657202,
        "key": "ch4",
    },
]

PRANKS = [
    {"id": "8810", "title": "💔 আপনি আমার গার্লফ্রেন্ডকে কল করেন কেন?"},
    {"id": "8805", "title": "🤢 গাজার মতো দুর্গন্ধ!"},
    {"id": "8803", "title": "🍕 পিজ্জা ডেলিভারি!"},
    {"id": "8809", "title": "📞 আপনি কেন আমাকে কল করেন?"},
    {"id": "8806", "title": "🔊 আপনার কামারার হৈচৈ আওয়াজ"},
    {"id": "8807", "title": "🐶 আপনার কুকুরটি খুবই বিরক্তিকর!"},
    {"id": "8804", "title": "🚕 আপনার ট্যাক্সি আপনার জন্য অপেক্ষা করছে!"},
    {"id": "8808", "title": "📡 আপনি আমার ওয়াই-ফাই চুরি করছেন!"},
]

PRANK_MAP = {p["id"]: p["title"] for p in PRANKS}
