import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import os
from datetime import datetime, timedelta, timezone

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

DB_NAME = "gofast.db"

# 🔹 Initialisation DB
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gofast (
                user_id INTEGER PRIMARY KEY,
                end_time TEXT
            )
        """)
        await db.commit()

# 🔹 Lancer un gofast
@bot.tree.command(name="gofast", description="Lancer un gofast (24h)")
async def gofast(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=False)  # ✅ IMPORTANT

    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM gofast WHERE user_id = ?", (user_id,))
        existing = await cursor.fetchone()

        if existing:
            await interaction.followup.send("❌ Tu as déjà un gofast en cours.", ephemeral=True)
            return

        end_time = now + timedelta(hours=24)

        await db.execute(
            "INSERT INTO gofast (user_id, end_time) VALUES (?, ?)",
            (user_id, end_time.isoformat())
        )
        await db.commit()

    await interaction.followup.send(
        f"🚗 Gofast lancé à {now.strftime('%H:%M')} (24h)"
    )

# 🔹 Voir temps restant
@bot.tree.command(name="temps", description="Voir le temps restant de ton gofast")
async def temps(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=True)  # ✅ IMPORTANT

    user_id = interaction.user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT end_time FROM gofast WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

        if not row:
            await interaction.followup.send("❌ Aucun gofast en cours.", ephemeral=True)
            return

        end_time = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)

        remaining = end_time - now

        if remaining.total_seconds() <= 0:
            await interaction.followup.send("✅ Ton gofast est prêt !", ephemeral=True)
        else:
            total_seconds = int(remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)

            await interaction.followup.send(
                f"⏳ Temps restant : {hours}h {minutes}min",
                ephemeral=True
            )

# 🔹 Supprimer le gofast (reset cooldown)
@bot.tree.command(name="stopgofast", description="Supprimer ton gofast en cours")
async def stopgofast(interaction: discord.Interaction):

    await interaction.response.defer(ephemeral=True)  # ✅ IMPORTANT

    user_id = interaction.user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM gofast WHERE user_id = ?", (user_id,))
        existing = await cursor.fetchone()

        if not existing:
            await interaction.followup.send("❌ Tu n'as aucun gofast en cours.", ephemeral=True)
            return

        await db.execute("DELETE FROM gofast WHERE user_id = ?", (user_id,))
        await db.commit()

    await interaction.followup.send("🗑️ Ton gofast a été supprimé !")

# 🔹 Vérification automatique
@tasks.loop(minutes=1)
async def check_gofast():
    now = datetime.now(timezone.utc)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, end_time FROM gofast")
        rows = await cursor.fetchall()

        for user_id, end_time_str in rows:
            end_time = datetime.fromisoformat(end_time_str)

            if now >= end_time:
                try:
                    user = await bot.fetch_user(user_id)

                    # 🔹 Tentative DM
                    try:
                        await user.send("🚗 Ton gofast est prêt !")
                    except:
                        # 🔹 fallback serveur
                        for guild in bot.guilds:
                            member = guild.get_member(user_id)

                            if member:
                                # chercher un channel valide
                                channel = None

                                # priorité au system channel
                                if guild.system_channel:
                                    channel = guild.system_channel

                                # fallback: premier salon texte accessible
                                if not channel:
                                    for c in guild.text_channels:
                                        if c.permissions_for(guild.me).send_messages:
                                            channel = c
                                            break

                                if channel:
                                    await channel.send(f"{member.mention} 🚗 Ton gofast est prêt !")
                                break

                except Exception as e:
                    print(f"Erreur check_gofast user {user_id} : {e}")

                # 🔹 suppression en base
                await db.execute("DELETE FROM gofast WHERE user_id = ?", (user_id,))

        await db.commit()

# 🔹 Ready
@bot.event
async def on_ready():
    await init_db()

    # ⚠️ Mets l'ID de ton serveur ici
    GUILD_ID = 871018561383071744
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)

    check_gofast.start()
    print(f"✅ Connecté en tant que {bot.user}")

bot.run(TOKEN)
