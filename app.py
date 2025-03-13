import os
import json
import discord
import logging
import asyncio
import aiohttp
import threading
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import hmac, hashlib

load_dotenv()

app = Flask(__name__)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

invites = []
members = []

token = os.getenv("DISCORD_TOKEN")
guild_id = int(os.getenv("DISCORD_GUILD_ID"))
intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents)

webhook_secret = os.getenv("WEBHOOK_SECRET")

def verify_webhook_signature(req):
    signature = req.headers.get("X-Signature")
    if not signature:
       	return False

    raw_data = req.data

    bom = b'\xef\xbb\xbf'
    raw_data = raw_data.replace(bom, b'')

    calculated_signature = hmac.new(webhook_secret.encode(), raw_data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated_signature, signature)

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

@app.route('/webhook/kick_member', methods=['POST'])
def kick_member():

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
                await member.kick(reason="action triggered via webhook")
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


@app.route('/webhook/create_invite', methods=['POST'])
def create_invite():
    if not verify_webhook_signature(request):
        return jsonify({"error": "unauthorized"}), 401
    if not bot.is_ready():
        return jsonify({"error": "bot not ready"}), 503

    async def _create():
        guild = bot.get_guild(guild_id)
        if guild and guild.text_channels:
            invite = await guild.text_channels[0].create_invite(max_age=86400, max_uses=1, unique=True)
            invites.append(invite.url)
            logger.info(f"created invite: {invite.url}")
            return invite.url
        else:
            logger.error("Guild or text channels not found.")
            raise Exception("guild or text channels not found")

    future = asyncio.run_coroutine_threadsafe(_create(), bot.loop)
    try:
        invite_url = future.result(timeout=10)
        return jsonify({"status": "success", "invite_url": invite_url}), 200
    except Exception as e:
        logger.error(f"Error creating invite: {e}")
        return jsonify({"error": "could not create invite"}), 500


@app.route('/webhook/get_last_invite', methods=['GET'])
def get_last_invite_webhook():
    if invites:
        return jsonify({"status": "success", "last_invite": invites[-1]}), 200
    return jsonify({"error": "no invites found"}), 404


@app.route('/webhook/get_all_invites', methods=['GET'])
def get_all_invites():
    if invites:
        return jsonify({"status": "success", "invites": invites}), 200
    return jsonify({"error": "no invites found"}), 404


@bot.event
async def on_ready():
    logger.info(f"discord bot is ready. logged in as {bot.user} (ID: {bot.user.id})")

    s = "7310c4c4c1d21ead56846af4502dfbc1"
    signature = hmac.new(s.encode(), b'', hashlib.sha256).hexdigest()
    print(signature)


@bot.event
async def on_member_join(member):
    logger.info(f"{member.name} joined the server.")
    members.append({"discord_id": member.id, "username": member.name})
    
    zapier_webhook_url = os.getenv("ZAPIER_WEBHOOK_URL")
    
    if zapier_webhook_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(zapier_webhook_url, json={"discord_id": member.id, "username": member.name}) as response:
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
