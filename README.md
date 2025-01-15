# discord_bot


I'll help you create a Discord bot using Python that can be integrated with Zapier. Here's a step-by-step guide:

First, create a Discord bot and get its token:

Copy1. Go to Discord Developer Portal (https://discord.com/developers/applications)
2. Click "New Application"
3. Give it a name and click "Create"
4. Go to the "Bot" section and click "Add Bot"
5. Copy the bot token (you'll need this later)

Here's a basic Discord bot code using discord.py:

```
pythonCopyimport discord
from discord.ext import commands
from flask import Flask, request, jsonify
import threading

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize Flask app
app = Flask(__name__)

# Your Discord bot token
DISCORD_TOKEN = 'YOUR_BOT_TOKEN'

# Store channel IDs where messages should be sent
CHANNEL_ID = None  # Replace with your channel ID

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

# API endpoint for Zapier to send messages
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        message = data.get('message', '')
        
        # Get the channel and send the message
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            bot.loop.create_task(channel.send(message))
            return jsonify({'status': 'success', 'message': 'Message sent'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Channel not found'}), 404
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Function to run the Flask server
def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Main function to run both Discord bot and Flask server
def main():
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # Run Discord bot
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    main()
```

Install required packages:

bashCopypip install discord.py flask

Deploy the bot:
You can deploy this bot on platforms like:


Heroku
DigitalOcean
AWS
Python Anywhere


To use with Zapier:

Copy1. Create a new Zap in Zapier
2. Choose your trigger (any app/event that you want to respond to)
3. For the action, choose "Webhooks by Zapier"
4. Select "POST" as the method
5. Use your deployed bot's URL as the webhook URL (e.g., https://your-domain.com/webhook)
6. Set the payload format to JSON with a structure like:
{
    "message": "Your message here"
}
Here's a more detailed version of the bot with additional features:

```
pythonCopyimport discord
from discord.ext import commands
from flask import Flask, request, jsonify
import threading
import logging
import os
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Initialize Flask app
app = Flask(__name__)

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', 'YOUR_CHANNEL_ID'))
API_KEY = os.getenv('API_KEY', 'YOUR_API_KEY')  # For securing webhook

# Store message history
message_history = []

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')

@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f'Error in {event}: {args} {kwargs}')

# Basic bot commands
@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f'Pong! Latency: {round(bot.latency * 1000)}ms')

@bot.command(name='history')
async def history(ctx):
    if not message_history:
        await ctx.send("No messages in history.")
        return
    
    history_text = "\n".join([f"{msg['timestamp']}: {msg['content']}" 
                             for msg in message_history[-10:]])
    await ctx.send(f"Last 10 messages:\n```{history_text}```")

# API endpoints
@app.route('/webhook', methods=['POST'])
def webhook():
    # Verify API key
    api_key = request.headers.get('X-API-Key')
    if api_key != API_KEY:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    try:
        data = request.json
        message = data.get('message', '')
        embed_data = data.get('embed', None)
        
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            return jsonify({'status': 'error', 'message': 'Channel not found'}), 404

        # Create embed if embed data is provided
        embed = None
        if embed_data:
            embed = discord.Embed(
                title=embed_data.get('title', ''),
                description=embed_data.get('description', ''),
                color=discord.Color.blue()
            )
            if 'fields' in embed_data:
                for field in embed_data['fields']:
                    embed.add_field(
                        name=field.get('name', ''),
                        value=field.get('value', ''),
                        inline=field.get('inline', True)
                    )

        # Send message and/or embed
        if message or embed:
            bot.loop.create_task(send_message(channel, message, embed))
            
            # Store in history
            message_history.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'content': message
            })
            if len(message_history) > 100:  # Keep only last 100 messages
                message_history.pop(0)
                
            return jsonify({'status': 'success', 'message': 'Message sent'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'No message or embed provided'}), 400
            
    except Exception as e:
        logger.error(f'Error in webhook: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

async def send_message(channel, content=None, embed=None):
    try:
        await channel.send(content=content, embed=embed)
    except Exception as e:
        logger.error(f'Error sending message: {str(e)}')
        raise

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

def main():
    try:
        # Start Flask server in a separate thread
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.start()
        
        # Run Discord bot
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f'Error in main: {str(e)}')

if __name__ == '__main__':
    main()
```

To use this enhanced version:

Set environment variables:

bashCopyexport DISCORD_TOKEN='your-token'
export CHANNEL_ID='your-channel-id'
export API_KEY='your-api-key'

In Zapier, when setting up the webhook:


Add the header: X-API-Key: your-api-key
You can send simple messages or complex embeds:

Simple message:

```
jsonCopy{
    "message": "Your message here"
}
Message with embed:
jsonCopy{
    "message": "Your message here",
    "embed": {
        "title": "Embed Title",
        "description": "Embed Description",
        "fields": [
            {
                "name": "Field 1",
                "value": "Value 1",
                "inline": true
            },
            {
                "name": "Field 2",
                "value": "Value 2",
                "inline": true
            }
        ]
    }
}
```
This enhanced version includes:

Error handling
Logging
Message history
API key authentication
Health check endpoint
Support for Discord embeds
Environment variable configuration
Basic bot commands

Remember to:

Keep your bot token and API key secure
Deploy the bot on a reliable hosting service
Use HTTPS for production deployments
Monitor the bot's logs for any issues
