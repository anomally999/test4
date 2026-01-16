import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from flask import Flask, request
from threading import Thread
from datetime import datetime
import traceback
# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # for username/nick if needed
intents.guilds = True
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    case_insensitive=True
)
app = Flask(__name__)
# Store per guild: log channel + webhook
# In production → use database (Redis, PostgreSQL on Render, json file, etc.)
log_channels = {} # guild_id → channel_id
log_webhooks = {} # guild_id → webhook_url
# ────────────────────────────────────────────────
# FLASK – Render health check & command endpoint
# ────────────────────────────────────────────────
@app.route('/')
def home():
    return "Bot is alive", 200
@app.route('/setlogchannel', methods=['POST'])
def setlogchannel_web():
    # Optional – you can make HTTP endpoint for /setlogchannel
    # But slash command is recommended
    return "Use /setlogchannel in Discord", 200
# ────────────────────────────────────────────────
# BOT EVENTS
# ────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} • {len(bot.guilds)} guilds")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)
@bot.tree.command(name="setlogchannel", description="Set the logging channel for this server")
@app_commands.default_permissions(manage_guild=True)
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not channel.permissions_for(interaction.guild.me).send_messages:
        return await interaction.response.send_message("I don't have permission to send messages there.", ephemeral=True)
    log_channels[interaction.guild.id] = channel.id
    # Create webhook (recommended for clean avatar/name + neon look)
    try:
        webhook = await channel.create_webhook(name="Neon Logger ★彡", reason="Logging system")
        log_webhooks[interaction.guild.id] = webhook.url
        await interaction.response.send_message(f"Logging channel set to {channel.mention}\nUsing beautiful webhook style.", ephemeral=True)
    except:
        # fallback to normal send
        log_webhooks[interaction.guild.id] = None
        await interaction.response.send_message(f"Logging channel set to {channel.mention}\n(Webhook creation failed – using normal messages)", ephemeral=True)
@bot.command(name="setlogchannel")
async def prefix_setlog(ctx, channel: discord.TextChannel):
    # Same logic as slash
    if not ctx.me.guild_permissions.manage_webhooks:
        return await ctx.send("I need `Manage Webhooks` permission.", delete_after=12)
    log_channels[ctx.guild.id] = channel.id
    try:
        webhook = await channel.create_webhook(name="Neon Logger ★彡")
        log_webhooks[ctx.guild.id] = webhook.url
        await ctx.send(f"→ Log channel: {channel.mention}\n→ Using neon webhook style", delete_after=20)
    except:
        log_webhooks[ctx.guild.id] = None
        await ctx.send(f"→ Log channel: {channel.mention}\n→ Webhook failed – fallback mode", delete_after=20)
# ────────────────────────────────────────────────
# BEAUTIFUL NEON-STYLE LOG EMBED
# ────────────────────────────────────────────────
def create_neon_embed(title, color=0x00f0ff):
    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.set_footer(text="Neon Logger 彡★ | " + datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    embed.set_thumbnail(url="https://i.imgur.com/YourCoolNeonIcon.png") # ← optional
    return embed
async def send_log(guild_id, embed: discord.Embed = None, files=None):
    channel_id = log_channels.get(guild_id)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    webhook_url = log_webhooks.get(guild_id)
    if webhook_url:
        from discord import SyncWebhook
        hook = SyncWebhook.from_url(webhook_url)
        try:
            hook.send(embed=embed, files=files, username="Neon Logger 彡★", avatar_url="https://i.imgur.com/neon-glow-avatar.png")
            return
        except:
            pass # fallback
    # Normal send fallback
    try:
        await channel.send(embed=embed, files=files)
    except:
        pass
# ────────────────────────────────────────────────
# MESSAGE EVENTS – very detailed logging
# ────────────────────────────────────────────────
@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.content == after.content:
        return
    if before.author.bot:
        return
    embed = create_neon_embed("✦ Message Edited", color=0xffd700) # gold/neon yellow
    embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    embed.add_field(name="Channel", value=before.channel.mention, inline=True)
    embed.add_field(name="Author", value=before.author.mention, inline=True)
    if before.content:
        embed.add_field(
            name="Before",
            value=f"```diff\n- {before.content[:900]}```" or "*Empty*",
            inline=False
        )
    if after.content:
        embed.add_field(
            name="After",
            value=f"```diff\n+ {after.content[:900]}```" or "*Empty*",
            inline=False
        )
    embed.add_field(name="Message ID", value=before.id, inline=True)
    embed.add_field(name="Jump", value=before.jump_url, inline=True)
    await send_log(before.guild.id, embed)
@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot:
        return
    if not message.attachments:  # Only log if there are attachments (vids/pics)
        return
    files = []
    for att in message.attachments:
        try:
            fp = await att.to_file(use_cached=True, filename=att.filename)
            files.append(fp)
        except:
            # If caching fails, skip or log URL instead, but since we want just the file, we'll skip failed ones
            pass
    if not files:  # If no files could be cached, skip
        return
    await send_log(message.guild.id, files=files)  # Send only the files, no embed
# You can add many more events: member join/leave/ban/roles/voice/nickname/channel create/delete etc.
# ────────────────────────────────────────────────
# RUN FLASK + BOT
# ────────────────────────────────────────────────
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
if __name__ == "__main__":
    # Start Flask in background thread (Render needs port listening)
    t = Thread(target=run_flask, daemon=True)
    t.start()
    # Run bot
    token = os.environ["DISCORD_TOKEN"]
    bot.run(token)
