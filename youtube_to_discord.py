from flask import Flask, request, abort, redirect, url_for, render_template_string, Response
import requests
import os
import threading
import time
import xml.etree.ElementTree as ET
import json
from functools import wraps

app = Flask(__name__)

# === CONFIGURATION ===
PUBLIC_URL = os.getenv("PUBLIC_URL")  # e.g. https://your-app.onrender.com/youtube-webhook
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")  # Protects the admin panel
CONTRIBUTOR_TOKEN = os.getenv("CONTRIBUTOR_TOKEN")  # Limited-access users
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
DISK_DIR = "/data"
os.makedirs(DISK_DIR, exist_ok=True)

CHANNELS_FILE = os.path.join(DISK_DIR, "channels.json")
WEBHOOKS_FILE = os.path.join(DISK_DIR, "webhooks.json")
POSTED_FILE = os.path.join(DISK_DIR, "posted_videos.json")
MAX_FILE_SIZE_BYTES = 1_000_000  # 1MB

# === DEFAULT VALUES ===
DEFAULT_CHANNELS = [
    "UCb9eK6mcBZmGPWl1UJ2wemA",
    "UCme1x5ySvBB8lGYsHpR4b6Q",
]
DEFAULT_WEBHOOK_MAP = {
    "GLOVE STATION": "https://discord.com/api/webhooks/1436874656224379033/_Nw5lGbnUD0xR8QmBxg5KrctPgKuIc1DU1fmVHcY-OXYloIbmDtC9LYeLTrje_IfSXim",
    "MK FIRE": "https://discord.com/api/webhooks/1436874897514303769/RD3TwnX2XJtOX-Qb20e6FDOdRhfBL8HPoqDMRF3rXyHQvyiqlE-brFhQJGYJrGBAW6UL",
    "INVETS": "https://discord.com/api/webhooks/1436874770728620174/ONn174GUKD8s4co19R6TVkmLMWW8sPwa0hfGnN2THB060D7nnAaJ3I_xLXHBG2iBqP8Q",
    "SAVE22 TRUCK SERIES": "https://discord.com/api/webhooks/1436873764083339335/-nU5XnnjzqUYZYih-_vjI-RqWrkE9LIZ8R-XpBHbae-t1hp_zVqm6L84hfSDhgZhy6GA",
    "CRUISIN CLASSICS": "https://discord.com/api/webhooks/1436874235296481310/khkApEcAstt_dpjlNMH2RzP_-TZMCQOEXfi-mEkZ7UiC4EJbW9ynvmMjvzXPWkqWN_xE",
    "LINCOLN TECH": "https://discord.com/api/webhooks/1436874472908001350/6OOWvxqeXLVAPwpODvvzgvtZjjJ0WVQpb1J-svt0aiyEHa7o56ehu93jRbd481IaVjLf",
    "GOAT TALK LIVE": "https://discord.com/api/webhooks/1437062385985650779/ORBmPYtKNvrwEa410L0LgF9QoE_gT-XoOJQ-kTuaEd4qxOefsofe1RfvqMCaj4Rpnupi"
}

# === HELPERS ===
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            print(f"⚠️ Failed to read {path}, using default.")
    save_json(path, default)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_posted_videos():
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            print("⚠️ Error reading posted_videos.json — starting fresh.")
            return set()
    return set()

def save_posted_videos():
    if os.path.exists(POSTED_FILE) and os.path.getsize(POSTED_FILE) > MAX_FILE_SIZE_BYTES:
        trimmed = list(posted_videos)[-1000:]
        with open(POSTED_FILE, "w") as f:
            json.dump(trimmed, f)
    else:
        with open(POSTED_FILE, "w") as f:
            json.dump(list(posted_videos), f)

CHANNELS = load_json(CHANNELS_FILE, DEFAULT_CHANNELS)
WEBHOOK_MAP = load_json(WEBHOOKS_FILE, DEFAULT_WEBHOOK_MAP)
posted_videos = load_posted_videos()

# === AUTH ===
def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        token = request.args.get("token") or request.headers.get("X-Admin-Token")
        if not ADMIN_TOKEN or token != ADMIN_TOKEN:
            return Response("Unauthorized", 401)
        return f(*args, **kwargs)
    return wrapped

def require_contributor(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        token = request.args.get("token") or request.headers.get("X-Contrib-Token")
        valid_tokens = [ADMIN_TOKEN, CONTRIBUTOR_TOKEN]
        if not token or token not in valid_tokens:
            return Response("Unauthorized", 401)
        return f(*args, **kwargs)
    return wrapped

# === YOUTUBE SUBSCRIPTION ===
def subscribe_to_youtube():
    """Subscribes all channels to YouTube PubSubHubBub."""
    if not PUBLIC_URL:
        print("❌ PUBLIC_URL not set — cannot subscribe.")
        return
    for ch in CHANNELS:
        topic = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={ch}"
        print(f"📡 Subscribing to {ch}")
        try:
            r = requests.post(HUB_URL, data={
                "hub.mode": "subscribe",
                "hub.topic": topic,
                "hub.callback": PUBLIC_URL,
                "hub.verify": "async"
            }, timeout=10)
            if r.status_code in [202, 204]:
                print(f"✅ Subscription accepted for {ch}")
            else:
                print(f"⚠️ Subscription failed ({r.status_code}): {r.text}")
        except Exception as e:
            print(f"❌ Error subscribing {ch}: {e}")

def auto_renew_subscriptions():
    while True:
        subscribe_to_youtube()
        print("⏰ Next resubscription in 30 days...")
        time.sleep(30 * 24 * 3600)

# === PUBLIC ROUTES ===
@app.route("/")
def health():
    return "✅ VSPEED YouTube → Discord Bot Running"

@app.route("/youtube-webhook", methods=["GET", "POST"])
def youtube_webhook():
    if request.method == "GET":
        return request.args.get("hub.challenge", ""), 200
    elif request.method == "POST":
        if not request.data:
            return "No data", 400
        try:
            root = ET.fromstring(request.data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                link = entry.find("atom:link", ns).attrib.get("href", "")
                if "v=" not in link:
                    continue
                video_id = link.split("v=")[-1]
                title = entry.find("atom:title", ns).text or "New Video"
                url = f"https://www.youtube.com/watch?v={video_id}"
                thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                if video_id in posted_videos:
                    continue
                posted_videos.add(video_id)
                save_posted_videos()

                for keyword, webhook in WEBHOOK_MAP.items():
                    if keyword in title.upper():
                        embed = {
                            "title": title,
                            "url": url,
                            "color": 0x1E90FF,
                            "image": {"url": thumb}
                        }
                        r = requests.post(webhook, json={
                            "username": "VSPEED 🎬 Broadcast Link",
                            "avatar_url": "https://www.svgrepo.com/show/355037/youtube.svg",
                            "embeds": [embed]
                        }, timeout=10)

                        # ✅ Verify Discord response
                        if r.status_code in [200, 204]:
                            print(f"✅ Posted '{title}' → {keyword}")
                        else:
                            print(f"⚠️ Discord post failed ({r.status_code}): {r.text[:200]}")

            return "OK", 200
        except Exception as e:
            print(f"⚠️ Error parsing XML: {e}")
            return "Error", 500
    abort(405)

# === ENTRY POINT ===
if __name__ == "__main__":
    threading.Thread(target=auto_renew_subscriptions, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
