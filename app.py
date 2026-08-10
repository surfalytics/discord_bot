import os
import time
import json
import discord
import logging
import asyncio
import aiohttp
import threading
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import hmac
import hashlib

load_dotenv()

app = Flask(__name__)

ALLOWED_ORIGINS = {
    "http://localhost:63342",
    "https://surfalytics.com",
    "https://www.surfalytics.com"
}

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Signature"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

invites = []
members = []

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
token = os.getenv("DISCORD_TOKEN")
guild_id = int(os.getenv("DISCORD_GUILD_ID"))
intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents)

webhook_secret = os.getenv("WEBHOOK_SECRET")

# Shared roadmap template ID (Surfalytics app)
SHARED_TEMPLATE_ID = "44079567-ba7d-44a9-b165-bb7751cd83ff"


def verify_webhook_signature(req):
    signature = req.headers.get("X-Signature")
    if not signature:
        return False
    raw_data = req.data
    bom = b'\xef\xbb\xbf'
    raw_data = raw_data.replace(bom, b'')
    calculated_signature = hmac.new(webhook_secret.encode(), raw_data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated_signature, signature)


def _roadmap_item_to_row(item):
    """Normalize one item to roadmap_template_items row (matches web app)."""
    return {
        "template_id": SHARED_TEMPLATE_ID,
        "parent_id": item.get("parent_id"),
        "item_type": item.get("item_type") or "step",
        "slug": item.get("slug"),
        "title": item.get("title") or "",
        "description": item.get("description"),
        "action_url": item.get("action_url"),
        "position": item.get("position", 0),
        "is_required": item.get("is_required", True),
        "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
    }


@app.route('/webhook/roadmap/items', methods=['POST', 'OPTIONS'])
def roadmap_items():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    if not verify_webhook_signature(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    items = body.get("items")
    if items is None and isinstance(body, dict) and "item_type" in body:
        items = [body]
    if not items or not isinstance(items, list):
        return jsonify({
            "error": "Provide a single item or { \"items\": [ ... ] }",
            "example": {"item_type": "step", "title": "New step", "position": 0}
        }), 400

    rows = [_roadmap_item_to_row(i) for i in items]
    url = f"{SUPABASE_URL}/rest/v1/roadmap_template_items"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return jsonify({"error": "Server misconfiguration"}), 500

    try:
        r = requests.post(url, json=rows, headers=headers, timeout=15)
    except Exception as e:
        logger.error(f"Roadmap insert request failed: {e}")
        return jsonify({"error": "Failed to call Supabase"}), 500

    if r.status_code not in (200, 201):
        logger.error(f"Supabase roadmap insert: {r.status_code} {r.text}")
        return jsonify({"error": r.text, "code": r.status_code}), 500

    data = r.json()
    return jsonify({"status": "success", "inserted": len(data), "data": data}), 201


@app.route('/webhook/send_message', methods=['POST'])
def send_message():
    raw_data = request.data
    logger.info("received raw data repr: " + repr(raw_data))
    bom = b'\xef\xbb\xbf'
    clean_data = raw_data.replace(bom, b'')
    try:
        data = json.loads(clean_data)
    except Exception as e:
        logger.error("Failed to parse JSON: " + str(e))
        return jsonify({"error": "Bad JSON: " + str(e)}), 400
    if not verify_webhook_signature(request):
        return jsonify({"error": "unauthorized"}), 401
    if not bot.is_ready():
        return jsonify({"error": "bot not ready"}), 503
    message = data.get("message")
    if not message:
        return jsonify({"error": "message is required"}), 400
    try:
        channel_id = int(data.get("channel_id"))
    except (ValueError, TypeError):
        return jsonify({"error": "invalid channel_id"}), 400
    thread_message = data.get("thread_message")
    thread_name = data.get("thread_name")

    async def _send():
        channel = bot.get_channel(channel_id)
        if channel:
            sent_message = await channel.send(message)
            thread = await sent_message.create_thread(name=thread_name, auto_archive_duration=1440)
            if thread_message:
                await thread.send(thread_message)
            logger.info(f"message and thread sent to channel {channel_id}")
        else:
            logger.error(f"channel with ID {channel_id} not found.")
            raise Exception("channel not found")

    future = asyncio.run_coroutine_threadsafe(_send(), bot.loop)
    try:
        future.result(timeout=10)
        return jsonify({"status": "success", "message": "message sent successfully"}), 200
    except Exception as e:
        logger.error(f"error sending message: {e}")
        return jsonify({"error": "failed to send message"}), 500


@app.route('/webhook/kick_member', methods=['POST', 'OPTIONS'])
def kick_member():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200
    raw = request.get_data()
    incoming_sig = request.headers.get("X-Signature")
    logger.info(f"raw payload  repr: {raw!r}")
    logger.info(f"incoming signature: {incoming_sig!r}")
    raw_data = request.data
    logger.info("received raw data: " + raw_data.decode('utf-8'))
    if not verify_webhook_signature(request):
        return jsonify({"error": "unauthorized"}), 401
    if not bot.is_ready():
        return jsonify({"error": "bot not ready"}), 503
    data = request.json
    try:
        discord_id = int(data.get("discord_id"))
    except (ValueError, TypeError):
        return jsonify({"error": "invalid discord_id"}), 400

    async def _kick():
        guild = bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(discord_id)
            if member:
                await member.kick(reason="User subscription end")
                logger.info(f"kicked member {discord_id} from guild {guild_id}")
            else:
                logger.error(f"member {discord_id} not found in guild.")
                raise Exception("member not found")
        else:
            logger.error("guild not found.")
            raise Exception("guild not found")

    future = asyncio.run_coroutine_threadsafe(_kick(), bot.loop)
    try:
        future.result(timeout=10)
        return jsonify({"status": "success", "message": f"Member {discord_id} kicked successfully"}), 200
    except Exception as e:
        logger.error(f"Error kicking member: {e}")
        return jsonify({"error": "failed to kick member"}), 500


@app.route('/webhook/create_invite', methods=['POST', 'OPTIONS'])
def create_invite():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200
    origin = request.headers.get("Origin")
    if origin not in ALLOWED_ORIGINS:
        if not verify_webhook_signature(request):
            return jsonify({"error": "unauthorized"}), 401
    if not bot.is_ready():
        return jsonify({"error": "bot not ready"}), 503

    async def _create():
        guild = bot.get_guild(guild_id)
        if guild and guild.text_channels:
            invite = await guild.text_channels[0].create_invite(
                max_age=86400,
                max_uses=1,
                unique=True
            )
            now = int(time.time())
            expires_at = now + (invite.max_age or 0)
            invites.append({"url": invite.url, "expires_at": expires_at})
            logger.info(f"created invite: {invite.url}, expires_at={expires_at}")
            return invite.url, expires_at
        else:
            logger.error("Guild or text channels not found.")
            raise Exception("guild or text channels not found")

    future = asyncio.run_coroutine_threadsafe(_create(), bot.loop)
    try:
        invite_url, expires_at = future.result(timeout=10)
        return jsonify({
            "status": "success",
            "invite_url": invite_url,
            "expires_at": expires_at
        }), 200
    except Exception as e:
        logger.error(f"Error creating invite: {e}")
        return jsonify({"error": "could not create invite"}), 500


@app.route('/webhook/get_last_invite', methods=['GET', 'OPTIONS'])
def get_last_invite_webhook():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200
    if not invites:
        return jsonify({"error": "no invites found"}), 404
    last = invites[-1]
    now = int(time.time())
    expires_at = last.get("expires_at")
    is_expired = expires_at is not None and now >= expires_at
    return jsonify({
        "status": "success",
        "invite_url": last["url"],
        "expires_at": expires_at,
        "is_expired": is_expired
    }), 200


@app.route('/webhook/get_all_invites', methods=['GET', 'OPTIONS'])
def get_all_invites():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200
    return jsonify({"status": "success", "invites": invites}), 200


@bot.event
async def on_member_join(member):
    logger.info(f"{member.name} joined the server.")
    members.append({"discord_id": member.id, "username": member.name})

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL or SUPABASE_SERVICE_KEY not set in environment.")
    else:
        rest_url = f"{SUPABASE_URL}/rest/v1/profiles"
        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        params = {"discord_id": f"eq.{member.id}"}
        payload = {"joined_discord": True}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(rest_url, params=params, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    if resp.status not in (200, 204):
                        logger.error(f"Supabase update failed: {resp.status} {text}")
                    else:
                        logger.info(f"Marked joined_discord=true for discord_id={member.id}")
        except Exception as e:
            logger.error(f"Error updating Supabase on join: {e}")

    zapier_webhook_url = os.getenv("ZAPIER_WEBHOOK_URL")
    if zapier_webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    zapier_webhook_url,
                    json={"discord_id": member.id, "username": member.name}
                ) as response:
                    if response.status != 200:
                        logger.error(f"Error calling join webhook: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Error calling join webhook: {str(e)}")
    else:
        logger.error("ZAPIER_WEBHOOK_URL not set in environment.")


@bot.event
async def on_member_remove(member):
    logger.info(f"{member.name} left the server.")


def run_discord_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        logger.error(f"Error running discord bot: {e}")
    finally:
        loop.run_until_complete(bot.close())
        loop.close()


if __name__ == "__main__":
    discord_thread = threading.Thread(target=run_discord_bot, name="thread")
    discord_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
