from flask import Flask, request, abort
import requests
import os
import xml.etree.ElementTree as ET

app = Flask(__name__)

# === CONFIGURATION ===
WEBHOOK_MAP = {
    "GLOVE STATION": "https://discord.com/api/webhooks/1436874656224379033/_Nw5lGbnUD0xR8QmBxg5KrctPgKuIc1DU1fmVHcY-OXYloIbmDtC9LYeLTrje_IfSXim",
    "MK FIRE": "https://discord.com/api/webhooks/1436874897514303769/RD3TwnX2XJtOX-Qb20e6FDOdRhfBL8HPoqDMRF3rXyHQvyiqlE-brFhQJGYJrGBAW6UL",
    "INVETS": "https://discord.com/api/webhooks/1436874770728620174/ONn174GUKD8s4co19R6TVkmLMWW8sPwa0hfGnN2THB060D7nnAaJ3I_xLXHBG2iBqP8Q",
    "SAVE22 TRUCK SERIES": "https://discord.com/api/webhooks/1436873764083339335/-nU5XnnjzqUYZYih-_vjI-RqWrkE9LIZ8R-XpBHbae-t1hp_zVqm6L84hfSDhgZhy6GA",
    "CRUSIN CLASSICS": "https://discord.com/api/webhooks/1436874235296481310/khkApEcAstt_dpjlNMH2RzP_-TZMCQOEXfi-mEkZ7UiC4EJbW9ynvmMjvzXPWkqWN_xE",
    "LINCOLN TECH": "https://discord.com/api/webhooks/1436874472908001350/6OOWvxqeXLVAPwpODvvzgvtZjjJ0WVQpb1J-svt0aiyEHa7o56ehu93jRbd481IaVjLf",
    "GOAT TALK LIVE": "https://discord.com/api/webhooks/1437062385985650779/ORBmPYtKNvrwEa410L0LgF9QoE_gT-XoOJQ-kTuaEd4qxOefsofe1RfvqMCaj4Rpnupi"
}


@app.route("/youtube-webhook", methods=["GET", "POST"])
def youtube_webhook():
    # 1️⃣ Subscription verification (YouTube hub check)
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        topic = request.args.get("hub.topic")

        print(f"✅ Verification request received: mode={mode}, topic={topic}")
        return challenge or "", 200

    # 2️⃣ Notification from YouTube
    elif request.method == "POST":
        if not request.data:
            return "No data", 400

        try:
            root = ET.fromstring(request.data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                title = entry.find("atom:title", ns).text
                video_id = entry.find("atom:link", ns).attrib["href"].split("v=")[-1]
                link = f"https://www.youtube.com/watch?v={video_id}"

                # Match keyword → post to Discord
                title_upper = title.upper()
                for keyword, webhook in WEBHOOK_MAP.items():
                    if keyword in title_upper:
                        print(f"🎯 New video detected: {title} → {keyword}")
                        try:
                            requests.post(webhook, json={
                                "username": "VSPEED 🎬 Broadcast Link",
                                "embeds": [{
                                    "title": title,
                                    "url": link,
                                    "color": 0x1E90FF
                                }]
                            }, timeout=10)
                        except Exception as e:
                            print(f"⚠️ Failed to send Discord message: {e}")

            return "OK", 200

        except Exception as e:
            print(f"⚠️ Error parsing XML: {e}")
            return "Error", 500

    else:
        abort(405)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
