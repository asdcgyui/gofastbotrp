import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import os
from datetime import datetime, timedelta

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
                start_time TEXT
            )
        """)
        await db.commit()

# 🔹 Lancer un gofast
@bot.tree.command(name="gofast", description="Lancer un gofast (24h)")
async def gofast(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM gofast WHERE user_id = ?", (user_id,))
        existing = await cursor.fetchone()

        if existing:
            await interaction.response.send_message("❌ Tu as déjà un gofast en cours.", ephemeral=True)
            return

        await db.execute(
            "INSERT INTO gofast (user_id, start_time) VALUES (?, ?)",
            (user_id, now.isoformat())
        )
        await db.commit()

    await interaction.response.send_message(
        f"🚗 Gofast lancé à {now.strftime('%H:%M')} (24h)",
        ephemeral=False
    )

# 🔹 Voir temps restant
@bot.tree.command(name="temps", description="Voir le temps restant de ton gofast")
async def temps(interaction: discord.Interaction):
    user_id = interaction.user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT start_time FROM gofast WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ Aucun gofast en cours.", ephemeral=True)
            return

        start_time = datetime.fromisoformat(row[0])
        end_time = start_time + timedelta(hours=24)
        remaining = end_time - datetime.now()

        if remaining.total_seconds() <= 0:
            await interaction.response.send_message("✅ Ton gofast est prêt !", ephemeral=True)
        else:
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(
                f"⏳ Temps restant : {hours}h {minutes}min",
                ephemeral=True
            )

# 🔹 Vérification automatique
@tasks.loop(minutes=1)
async def check_gofast():
    now = datetime.now()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, start_time FROM gofast")
        rows = await cursor.fetchall()

        for user_id, start_time_str in rows:
            start_time = datetime.fromisoformat(start_time_str)
            end_time = start_time + timedelta(hours=24)

            if now >= end_time:
                user = await bot.fetch_user(user_id)

                # 🔹 DM
                try:
                    await user.send("🚗 Ton gofast est prêt !")
                except:
                    # 🔹 fallback mention dans serveur
                    for guild in bot.guilds:
                        member = guild.get_member(user_id)
                        if member:
                            channel = guild.system_channel
                            if channel:
                                await channel.send(f"{member.mention} 🚗 Ton gofast est prêt !")
                            break

                await db.execute("DELETE FROM gofast WHERE user_id = ?", (user_id,))
        await db.commit()

# 🔹 Ready
@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    check_gofast.start()
    print(f"✅ Connecté en tant que {bot.user}")

bot.run(TOKEN)