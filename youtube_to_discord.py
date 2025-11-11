from flask import Flask, request, abort
import requests
import os
import threading
import time
import xml.etree.ElementTree as ET
import json

app = Flask(__name__)

# === CONFIGURATION ===
CHANNELS = [
    "UCb9eK6mcBZmGPWl1UJ2wemA",
    "UCme1x5ySvBB8lGYsHpR4b6Q",
]

WEBHOOK_MAP = {
    "GLOVE STATION": "https://discord.com/api/webhooks/1436874656224379033/_Nw5lGbnUD0xR8QmBxg5KrctPgKuIc1DU1fmVHcY-OXYloIbmDtC9LYeLTrje_IfSXim",
    "MK FIRE": "https://discord.com/api/webhooks/1436874897514303769/RD3TwnX2XJtOX-Qb20e6FDOdRhfBL8HPoqDMRF3rXyHQvyiqlE-brFhQJGYJrGBAW6UL",
    "INVETS": "https://discord.com/api/webhooks/1436874770728620174/ONn174GUKD8s4co19R6TVkmLMWW8sPwa0hfGnN2THB060D7nnAaJ3I_xLXHBG2iBqP8Q",
    "SAVE22 TRUCK SERIES": "https://discord.com/api/webhooks/1436873764083339335/-nU5XnnjzqUYZYih-_vjI-RqWrkE9LIZ8R-XpBHbae-t1hp_zVqm6L84hfSDhgZhy6GA",
    "CRUISIN CLASSICS": "https://discord.com/api/webhooks/1436874235296481310/khkApEcAstt_dpjlNMH2RzP_-TZMCQOEXfi-mEkZ7UiC4EJbW9ynvmMjvzXPWkqWN_xE",
    "LINCOLN TECH": "https://discord.com/api/webhooks/1436874472908001350/6OOWvxqeXLVAPwpODvvzgvtZjjJ0WVQpb1J-svt0aiyEHa7o56ehu93jRbd481IaVjLf",
    "GOAT TALK LIVE": "https://discord.com/api/webhooks/1437062385985650779/ORBmPYtKNvrwEa410L0LgF9QoE_gT-XoOJQ-kTuaEd4qxOefsofe1RfvqMCaj4Rpnupi"
}

CALLBACK_URL = os.getenv("PUBLIC_URL")  # e.g. https://youtube-discord-pubsub.onrender.com/youtube-webhook
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"

# ✅ Persistent file path — stored on Render disk
POSTED_FILE = "/data/posted_videos.json"
MAX_FILE_SIZE_BYTES = 1_000_000  # ≈ 1 MB limit

# === PERSISTENCE HELPERS ===
def load_posted_videos():
    """Load posted video IDs from persistent disk."""
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            try:
                return set(json.load(f))
            except Exception:
                print("⚠️ Error reading posted_videos.json — starting fresh.")
                return set()
    return set()

def save_posted_videos():
    """Save posted video IDs back to persistent disk, trimming if too large."""
    if os.path.exists(POSTED_FILE):
        size = os.path.getsize(POSTED_FILE)
        if size > MAX_FILE_SIZE_BYTES:
            print(f"⚠️ posted_videos.json exceeded {MAX_FILE_SIZE_BYTES} bytes, trimming older entries...")
            trimmed = list(posted_videos)[-1000:]
            with open(POSTED_FILE, "w") as f:
                json.dump(trimmed, f)
            return

    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted_videos), f)

# Load existing IDs at startup
posted_videos = load_posted_videos()


# === SUBSCRIPTION FUNCTIONS ===
def subscribe_to_youtube():
    """Subscribe to YouTube PubSubHubbub for all channels."""
    for channel_id in CHANNELS:
        topic_url = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"
        print(f"📡 Subscribing to channel {channel_id}...")
        try:
            resp = requests.post(HUB_URL, data={
                "hub.mode": "subscribe",
                "hub.topic": topic_url,
                "hub.callback": CALLBACK_URL,
                "hub.verify": "async"
            }, timeout=10)
            if resp.status_code in [202, 204]:
                print(f"✅ Subscription request accepted for {channel_id}")
            else:
                print(f"⚠️ Subscription error for {channel_id}: {resp.status_code}")
        except Exception as e:
            print(f"❌ Error subscribing to {channel_id}: {e}")


def auto_renew_subscriptions():
    """Automatically re-subscribe every 30 days."""
    while True:
        subscribe_to_youtube()
        print("⏰ Next resubscription in 30 days...")
        time.sleep(30 * 24 * 3600)


# === FLASK ROUTES ===
@app.route("/")
def health():
    return "✅ VSPEED YouTube → Discord Bot Running"


@app.route("/resubscribe")
def resubscribe():
    subscribe_to_youtube()
    return "🔁 Resubscription triggered manually!", 200


@app.route("/youtube-webhook", methods=["GET", "POST"])
def youtube_webhook():
    if request.method == "GET":
        challenge = request.args.get("hub.challenge")
        topic = request.args.get("hub.topic")
        print(f"✅ Verification request from {topic}")
        return challenge or "", 200

    elif request.method == "POST":
        if not request.data:
            return "No data", 400

        try:
            root = ET.fromstring(request.data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                video_id = entry.find("atom:link", ns).attrib["href"].split("v=")[-1]
                title = entry.find("atom:title", ns).text
                link = f"https://www.youtube.com/watch?v={video_id}"
                thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                # 🚫 Skip if already posted
                if video_id in posted_videos:
                    print(f"⚠️ Skipping duplicate: {video_id}")
                    continue

                # ✅ Mark as posted
                posted_videos.add(video_id)
                save_posted_videos()

                title_upper = title.upper()
                for keyword, webhook in WEBHOOK_MAP.items():
                    if keyword in title_upper:
                        print(f"🎯 New video detected: {title} → {keyword}")
                        embed = {
                            "title": title,
                            "url": link,
                            "color": 0x1E90FF,
                            "image": {"url": thumb}
                        }
                        requests.post(webhook, json={
                            "username": "VSPEED 🎬 Broadcast Link",
                            "avatar_url": "https://www.svgrepo.com/show/355037/youtube.svg",
                            "embeds": [embed]
                        }, timeout=10)

            return "OK", 200

        except Exception as e:
            print(f"⚠️ Error parsing XML: {e}")
            return "Error", 500

    else:
        abort(405)


# === MAIN ENTRY POINT ===
if __name__ == "__main__":
    threading.Thread(target=auto_renew_subscriptions, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
