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

# ─────────────────────────────────────────
# Initialisation DB
# ─────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Créer la table si elle n'existe pas
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gofast (
                user_id INTEGER PRIMARY KEY,
                end_time TEXT
            )
        """)
        await db.commit()

        # Migration : ajouter end_time si la colonne est absente (ancienne DB)
        cursor = await db.execute("PRAGMA table_info(gofast)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "end_time" not in columns:
            print("[init_db] Migration : ajout de la colonne end_time")
            await db.execute("ALTER TABLE gofast ADD COLUMN end_time TEXT")
            await db.commit()
        
        print("[init_db] Base de données prête.")

# ─────────────────────────────────────────
# /gofast — Lancer un gofast (24h)
# ─────────────────────────────────────────
@bot.tree.command(name="gofast", description="Lancer un gofast (24h)")
async def gofast(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now(timezone.utc)

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT end_time FROM gofast WHERE user_id = ?", (user_id,))
            existing = await cursor.fetchone()

            if existing:
                end_time = datetime.fromisoformat(existing[0])
                remaining = end_time - now
                if remaining.total_seconds() > 0:
                    total_seconds = int(remaining.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    await interaction.response.send_message(
                        f"❌ Tu as déjà un gofast en cours. Temps restant : **{hours}h {minutes}min**",
                        ephemeral=True
                    )
                    return
                else:
                    # Expiré mais pas encore nettoyé, on remplace
                    await db.execute("DELETE FROM gofast WHERE user_id = ?", (user_id,))
                    await db.commit()

            end_time = now + timedelta(hours=24)
            await db.execute(
                "INSERT INTO gofast (user_id, end_time) VALUES (?, ?)",
                (user_id, end_time.isoformat())
            )
            await db.commit()

        await interaction.response.send_message(
            f"🚗 **Gofast lancé !** Il sera prêt dans **24h** (à {end_time.strftime('%H:%M')} UTC)."
        )

    except Exception as e:
        print(f"[gofast] Erreur : {e}")
        try:
            await interaction.response.send_message("❌ Une erreur est survenue. Réessaie.", ephemeral=True)
        except Exception:
            pass

# ─────────────────────────────────────────
# /temps — Voir le temps restant
# ─────────────────────────────────────────
@bot.tree.command(name="temps", description="Voir le temps restant de ton gofast")
async def temps(interaction: discord.Interaction):
    user_id = interaction.user.id

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT end_time FROM gofast WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ Aucun gofast en cours.", ephemeral=True)
            return

        end_time = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        remaining = end_time - now

        if remaining.total_seconds() <= 0:
            await interaction.response.send_message("✅ Ton gofast est **prêt** ! Lance-le avec `/gofast`.", ephemeral=True)
        else:
            total_seconds = int(remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(
                f"⏳ Temps restant avant le prochain gofast : **{hours}h {minutes}min**",
                ephemeral=True
            )

    except Exception as e:
        print(f"[temps] Erreur : {e}")
        try:
            await interaction.response.send_message("❌ Une erreur est survenue. Réessaie.", ephemeral=True)
        except Exception:
            pass

# ─────────────────────────────────────────
# /stopgofast — Arrêter le gofast en cours
# ─────────────────────────────────────────
@bot.tree.command(name="stopgofast", description="Supprimer ton gofast en cours")
async def stopgofast(interaction: discord.Interaction):
    user_id = interaction.user.id

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT user_id FROM gofast WHERE user_id = ?", (user_id,))
            existing = await cursor.fetchone()

            if not existing:
                await interaction.response.send_message("❌ Tu n'as aucun gofast en cours.", ephemeral=True)
                return

            await db.execute("DELETE FROM gofast WHERE user_id = ?", (user_id,))
            await db.commit()

        await interaction.response.send_message(
            "🗑️ Ton gofast a été **arrêté**. Tu peux en relancer un avec `/gofast`.",
            ephemeral=True
        )

    except Exception as e:
        print(f"[stopgofast] Erreur : {e}")
        try:
            await interaction.response.send_message("❌ Une erreur est survenue. Réessaie.", ephemeral=True)
        except Exception:
            pass

# ─────────────────────────────────────────
# Vérification automatique toutes les minutes
# ─────────────────────────────────────────
@tasks.loop(minutes=1)
async def check_gofast():
    now = datetime.now(timezone.utc)
    to_delete = []

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT user_id, end_time FROM gofast")
            rows = await cursor.fetchall()

        for user_id, end_time_str in rows:
            try:
                end_time = datetime.fromisoformat(end_time_str)
            except ValueError:
                to_delete.append(user_id)
                continue

            if now >= end_time:
                to_delete.append(user_id)
                try:
                    user = await bot.fetch_user(user_id)
                    notified = False

                    # Tentative DM
                    try:
                        await user.send("🚗 Ton gofast est **prêt** ! Tu peux le relancer avec `/gofast`.")
                        notified = True
                    except discord.Forbidden:
                        pass

                    # Fallback : mention dans un salon du serveur
                    if not notified:
                        for guild in bot.guilds:
                            member = guild.get_member(user_id)
                            if not member:
                                continue
                            channel = guild.system_channel
                            if not channel or not channel.permissions_for(guild.me).send_messages:
                                channel = next(
                                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                                    None
                                )
                            if channel:
                                await channel.send(f"{member.mention} 🚗 Ton gofast est **prêt** !")
                                break

                except Exception as e:
                    print(f"[check_gofast] Erreur notif user {user_id} : {e}")

        # Suppression groupée après l'itération
        if to_delete:
            async with aiosqlite.connect(DB_NAME) as db:
                await db.executemany("DELETE FROM gofast WHERE user_id = ?", [(uid,) for uid in to_delete])
                await db.commit()

    except Exception as e:
        print(f"[check_gofast] Erreur globale : {e}")

@check_gofast.before_loop
async def before_check():
    await bot.wait_until_ready()

# ─────────────────────────────────────────
# Ready
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    await init_db()

    GUILD_ID = 871018561383071744  # ⚠️ Ton ID de serveur
    guild = discord.Object(id=GUILD_ID)

    try:
        await bot.tree.sync(guild=guild)
        print(f"✅ Commandes synchronisées sur le serveur {GUILD_ID}")
    except Exception as e:
        print(f"❌ Erreur sync commandes : {e}")

    if not check_gofast.is_running():
        check_gofast.start()

    print(f"✅ Connecté en tant que {bot.user}")

bot.run(TOKEN)
