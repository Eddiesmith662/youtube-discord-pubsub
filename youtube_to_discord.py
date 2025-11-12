from flask import Flask, request, Response
import requests
import os
import threading
import time
import xml.etree.ElementTree as ET
import json

app = Flask(__name__)

# === CONFIGURATION ===
PUBLIC_URL = os.getenv("PUBLIC_URL")  # e.g. https://your-app.onrender.com
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
DISK_DIR = "/data"
os.makedirs(DISK_DIR, exist_ok=True)

POSTED_FILE = os.path.join(DISK_DIR, "posted_videos.json")
MAX_FILE_SIZE_BYTES = 1_000_000  # 1MB

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

# === STORAGE ===
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
    """Save posted videos, trimming old ones if the file gets too large."""
    if os.path.exists(POSTED_FILE) and os.path.getsize(POSTED_FILE) > MAX_FILE_SIZE_BYTES:
        trimmed = list(posted_videos)[-1000:]
        with open(POSTED_FILE, "w") as f:
            json.dump(trimmed, f)
    else:
        with open(POSTED_FILE, "w") as f:
            json.dump(list(posted_videos), f)

posted_videos = load_posted_videos()

# === RATE-LIMIT SAFE DISCORD POST ===
def safe_post_to_discord(webhook, payload, keyword):
    """Send a message to Discord while respecting rate limits."""
    try:
        response = requests.post(webhook, json=payload, timeout=10)

        # ✅ Success
        if response.status_code == 204:
            print(f"✅ Sent to Discord: {keyword}")
            return

        # 🚫 Rate limited
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "2")
            print(f"⏳ Rate limited for {keyword}. Retrying in {retry_after}s...")
            try:
                time.sleep(float(retry_after))
            except ValueError:
                time.sleep(2)
            retry_response = requests.post(webhook, json=payload, timeout=10)
            if retry_response.status_code == 204:
                print(f"✅ Retried successfully for {keyword}")
            else:
                print(f"⚠️ Retry failed ({retry_response.status_code}) for {keyword}")
            return

        # ❌ Webhook deleted
        if response.status_code == 404:
            print(f"❌ Webhook invalid or deleted for {keyword} (404)")
            return

        print(f"⚠️ Discord returned {response.status_code}: {response.text[:80]}")

    except Exception as e:
        print(f"💥 Error posting to Discord ({keyword}): {e}")

# === YOUTUBE SUBSCRIPTION ===
def subscribe_to_youtube():
    if not PUBLIC_URL:
        print("❌ PUBLIC_URL not set — cannot subscribe.")
        return
    callback = f"{PUBLIC_URL}/youtube-webhook"
    for ch in CHANNELS:
        topic = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={ch}"
        print(f"📡 Subscribing to {ch}")
        try:
            r = requests.post(HUB_URL, data={
                "hub.mode": "subscribe",
                "hub.topic": topic,
                "hub.callback": callback,
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

# === FLASK ROUTES ===
@app.route("/")
def health():
    return "✅ VSPEED YouTube → Discord (PubSubHubbub) Running"

@app.route("/youtube-webhook", methods=["GET", "POST"])
def youtube_webhook():
    if request.method == "GET":
        challenge = request.args.get("hub.challenge")
        print(f"🔗 Verification challenge: {challenge}")
        return Response(challenge, 200)

    elif request.method == "POST":
        if not request.data:
            return "No data", 400

        try:
            print("📨 Incoming YouTube notification...")
            root = ET.fromstring(request.data)
            ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

            for entry in root.findall("atom:entry", ns):
                video_id_tag = entry.find("yt:videoId", ns)
                if video_id_tag is None:
                    continue
                video_id = video_id_tag.text.strip()

                title_tag = entry.find("atom:title", ns)
                title = title_tag.text if title_tag is not None else "New Video"
                url = f"https://www.youtube.com/watch?v={video_id}"
                thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                if video_id in posted_videos:
                    print(f"⏩ Already posted: {title}")
                    continue

                posted_videos.add(video_id)
                save_posted_videos()
                print(f"🎥 New video detected: {title}")

                for keyword, webhook in WEBHOOK_MAP.items():
                    if keyword in title.upper():
                        embed = {
                            "title": title,
                            "url": url,
                            "color": 0x1E90FF,
                            "image": {"url": thumb}
                        }
                        payload = {
                            "username": "VSPEED 🎬 Broadcast Link",
                            "avatar_url": "https://www.svgrepo.com/show/355037/youtube.svg",
                            "embeds": [embed]
                        }
                        safe_post_to_discord(webhook, payload, keyword)
                        time.sleep(1)

            return "OK", 200

        except Exception as e:
            print(f"⚠️ Error parsing notification: {e}")
            return "Error", 500

@app.route("/test-discord")
def test_discord():
    """Test all stored Discord webhooks for validity while respecting rate limits."""
    results = []
    for keyword, webhook in WEBHOOK_MAP.items():
        try:
            response = requests.post(webhook, json={
                "content": f"🧪 Test message from VSPEED for **{keyword}** webhook."
            }, timeout=10)

            if response.status_code == 204:
                results.append(f"✅ {keyword}: OK")
            elif response.status_code == 404:
                results.append(f"❌ {keyword}: Invalid or deleted (404 Unknown Webhook)")
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "2")
                results.append(f"⏳ {keyword}: Rate limited — retry after {retry_after}s")
                try:
                    time.sleep(float(retry_after))
                except ValueError:
                    time.sleep(2)
            else:
                results.append(f"⚠️ {keyword}: Unexpected {response.status_code} ({response.text[:80]})")

        except Exception as e:
            results.append(f"💥 {keyword}: Error - {e}")

        time.sleep(1)

    print("\n".join(results))
    return "<br>".join(results), 200


# === ENTRY POINT ===
if __name__ == "__main__":
    threading.Thread(target=auto_renew_subscriptions, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
