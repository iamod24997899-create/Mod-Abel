import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("MEMBERCOUNT_TOKEN")

# Only this Discord account receives the owner permission bypass.
OWNER_USER_ID = 899026686581039144

if not TOKEN:
    raise RuntimeError("MEMBERCOUNT_TOKEN is not set.")

PREFIX_DB = "prefixes.db"
MESSAGES_DB = "messages.db"
AFK_DB = "afk.db"
WARNINGS_DB = "warnings.db"
WELCOME_LEAVE_DB = "welcome_leave.db"

MAX_WARNINGS = 3
WARNING_TIMEOUT_SECONDS = 60 * 60
MAX_MUTE_SECONDS = 28 * 24 * 60 * 60


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.presences = True


# =========================================================
# PREFIX DATABASE
# =========================================================

def init_prefix_db():
    with sqlite3.connect(PREFIX_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prefixes (
                guild_id INTEGER PRIMARY KEY,
                prefix TEXT NOT NULL
            )
        """)
        conn.commit()


def get_prefix(guild_id):
    with sqlite3.connect(PREFIX_DB) as conn:
        row = conn.execute(
            "SELECT prefix FROM prefixes WHERE guild_id = ?",
            (guild_id,)
        ).fetchone()

    return row[0] if row else "?"


def set_prefix(guild_id, prefix):
    with sqlite3.connect(PREFIX_DB) as conn:
        conn.execute("""
            INSERT INTO prefixes (guild_id, prefix)
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET prefix = excluded.prefix
        """, (guild_id, prefix))
        conn.commit()


def get_bot_prefix(bot, message):
    if message.guild is None:
        return "?"

    return get_prefix(message.guild.id)


# =========================================================
# MESSAGE DATABASE
# =========================================================

def init_messages_db():

    with sqlite3.connect(MESSAGES_DB) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_adjustments (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                amount INTEGER NOT NULL,
                reference_real INTEGER NOT NULL DEFAULT 0,
                period_start TEXT,
                PRIMARY KEY (guild_id, user_id, period)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_settings (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)

        conn.commit()


def messages_enabled(guild_id):

    with sqlite3.connect(MESSAGES_DB) as conn:
        row = conn.execute("""
            SELECT enabled
            FROM message_settings
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()

    if row is None:
        return True

    return bool(row[0])


def set_messages_enabled(guild_id, enabled):

    with sqlite3.connect(MESSAGES_DB) as conn:
        conn.execute("""
            INSERT INTO message_settings (
                guild_id,
                enabled
            )
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET enabled = excluded.enabled
        """, (
            guild_id,
            1 if enabled else 0
        ))

        conn.commit()


# =========================================================
# AFK DATABASE
# =========================================================

def init_afk_db():

    with sqlite3.connect(AFK_DB) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS afk (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                original_nick TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS afk_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                afk_user_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()


# =========================================================
# WARNINGS DATABASE
# =========================================================

def init_warnings_db():

    with sqlite3.connect(WARNINGS_DB) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()


# =========================================================
# WELCOME / LEAVE DATABASE
# =========================================================

def init_welcome_leave_db():

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS welcome_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS leave_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS autorole_settings (
                guild_id INTEGER PRIMARY KEY,
                role_id INTEGER NOT NULL
            )
        """)

        conn.commit()


def set_welcome_channel(guild_id, channel_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:

        conn.execute("""
            INSERT INTO welcome_settings (
                guild_id,
                channel_id
            )
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET channel_id = excluded.channel_id
        """, (
            guild_id,
            channel_id
        ))

        conn.commit()


def set_leave_channel(guild_id, channel_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:

        conn.execute("""
            INSERT INTO leave_settings (
                guild_id,
                channel_id
            )
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET channel_id = excluded.channel_id
        """, (
            guild_id,
            channel_id
        ))

        conn.commit()


def get_welcome_channel(guild_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:
        row = conn.execute("""
            SELECT channel_id
            FROM welcome_settings
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()

    return row[0] if row else None


def get_leave_channel(guild_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:
        row = conn.execute("""
            SELECT channel_id
            FROM leave_settings
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()

    return row[0] if row else None


# =========================================================
# INIT DATABASES
# =========================================================

init_prefix_db()
init_messages_db()
init_afk_db()
init_warnings_db()
init_welcome_leave_db()


# =========================================================
# BOT
# =========================================================

class MyBot(commands.Bot):

    async def setup_hook(self):

        print("🔄 Syncing global slash commands...")

        try:
            synced = await self.tree.sync()
            print(f"✅ {len(synced)} global commands synced.")

        except Exception as e:
            print(f"❌ Slash command sync error: {e}")


bot = MyBot(
    command_prefix=get_bot_prefix,
    intents=intents,
    help_command=None
)


def has_permissions_or_owner(**required_permissions):
    """Prefix-command check: the configured owner bypasses user permission checks."""
    async def predicate(ctx):
        if ctx.author.id == OWNER_USER_ID:
            return True
        if ctx.guild is None:
            return False
        permissions = ctx.author.guild_permissions
        return all(getattr(permissions, name, False) for name in required_permissions)
    return commands.check(predicate)


def app_has_permissions_or_owner(**required_permissions):
    """Slash-command check: the configured owner bypasses user permission checks."""
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == OWNER_USER_ID:
            return True
        if interaction.guild is None:
            return False
        permissions = interaction.user.guild_permissions
        return all(getattr(permissions, name, False) for name in required_permissions)
    return predicate


# =========================================================
# UTILS
# =========================================================

def utcnow():
    return datetime.now(timezone.utc)


async def asyncio_sleep(seconds):

    import asyncio

    await asyncio.sleep(seconds)


# =========================================================
# AUTOMATIC RANK DETECTION
# =========================================================

SPECIAL_ROLE_WORDS = {
    "verified", "verify", "verification",
    "vip",
    "booster", "boost", "nitro",
    "bot", "bots",
    "muted", "mute",
    "ticket", "tickets",
    "giveaway", "giveaways",
    "colour", "color",
    "custom",
    "media",
    "friend", "friends",
    "guest",
    "support", "supporter",
    "donator", "donate",
    "subscriber",
    "streamer", "youtuber",
    "content", "partner",
    "notification", "notifications",
    "ping",
    "announcement", "announcements",
    "private"
}


def looks_like_special_role(role):

    name = role.name.lower().strip()

    if role.is_default():
        return True

    if role.managed:
        return True

    for word in SPECIAL_ROLE_WORDS:
        if word in name:
            return True

    return False


def get_automatic_rank_roles(guild):

    roles = []

    for role in guild.roles:

        if role.is_default():
            continue

        if role.managed:
            continue

        if looks_like_special_role(role):
            continue

        roles.append(role)

    roles.sort(key=lambda role: role.position)

    return roles


def get_current_rank(member):

    rank_roles = get_automatic_rank_roles(member.guild)

    member_rank_roles = [
        role for role in member.roles
        if role in rank_roles
    ]

    if not member_rank_roles:
        return None

    return max(
        member_rank_roles,
        key=lambda role: role.position
    )


def get_promote_roles(member):

    guild = member.guild
    bot_member = guild.me

    if bot_member is None:
        return []

    rank_roles = get_automatic_rank_roles(guild)
    current_rank = get_current_rank(member)

    current_position = (
        current_rank.position
        if current_rank
        else -1
    )

    available = []

    for role in rank_roles:

        if role.position <= current_position:
            continue

        if role >= bot_member.top_role:
            continue

        available.append(role)

    available.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return available


def get_demote_roles(member):

    guild = member.guild
    bot_member = guild.me

    if bot_member is None:
        return []

    rank_roles = get_automatic_rank_roles(guild)
    current_rank = get_current_rank(member)

    if current_rank is None:
        return []

    available = []

    for role in rank_roles:

        if role.position >= current_rank.position:
            continue

        if role >= bot_member.top_role:
            continue

        available.append(role)

    available.sort(
        key=lambda role: role.position,
        reverse=True
    )

    return available


# =========================================================
# PROMOTE / DEMOTE MENU
# =========================================================

class RoleSelect(discord.ui.Select):

    def __init__(self, target_member, action, roles):

        self.target_member = target_member
        self.action = action

        options = []

        for role in roles[:25]:

            description = (
                "Promote to this rank"
                if action == "promote"
                else "Demote to this rank"
            )

            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    description=description,
                    value=str(role.id)
                )
            )

        super().__init__(
            placeholder="Select a rank...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction):

        role_id = int(self.values[0])

        new_role = interaction.guild.get_role(role_id)

        if new_role is None:

            await interaction.response.send_message(
                "❌ That role no longer exists.",
                ephemeral=True
            )

            return

        success, old_role, error = await change_member_rank(
            self.target_member,
            new_role
        )

        if not success:

            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True
            )

            return

        old_text = (
            old_role.mention
            if old_role
            else "None"
        )

        title = (
            "⬆️ Member Promoted"
            if self.action == "promote"
            else "⬇️ Member Demoted"
        )

        embed = discord.Embed(
            title=title,
            color=discord.Color.green()
        )

        embed.description = (
            f"**Member:** {self.target_member.mention}\n\n"
            f"**Old rank:** {old_text}\n"
            f"**New rank:** {new_role.mention}"
        )

        await interaction.response.edit_message(
            embed=embed,
            view=None
        )


class RolePanel(discord.ui.View):

    def __init__(self, target_member, action, roles):

        super().__init__(timeout=60)

        self.target_member = target_member
        self.action = action

        self.add_item(
            RoleSelect(
                target_member,
                action,
                roles
            )
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger
    )
    async def cancel(self, interaction, button):

        await interaction.response.edit_message(
            content="❌ Rank change cancelled.",
            embed=None,
            view=None
        )


async def change_member_rank(member, new_role):

    guild = member.guild
    bot_member = guild.me

    if bot_member is None:
        return False, None, "I couldn't detect my bot role."

    if new_role >= bot_member.top_role:
        return False, None, (
            "I cannot manage that role because it is above my highest role."
        )

    if member == bot_member:
        return False, None, "I cannot change my own rank."

    if member.top_role >= bot_member.top_role:
        return False, None, (
            "I cannot change this user's rank because their highest "
            "role is equal to or above mine."
        )

    current_rank = get_current_rank(member)

    if current_rank == new_role:
        return False, current_rank, "The user already has that rank."

    if current_rank:

        try:

            await member.remove_roles(
                current_rank,
                reason="Rank changed by Promote/Demote"
            )

        except discord.Forbidden:

            return False, current_rank, (
                "I don't have permission to remove the old rank."
            )

        except discord.HTTPException:

            return False, current_rank, (
                "Discord rejected the role change."
            )

    try:

        await member.add_roles(
            new_role,
            reason="Rank changed by Promote/Demote"
        )

    except discord.Forbidden:

        if current_rank:
            try:
                await member.add_roles(
                    current_rank,
                    reason="Restoring previous rank"
                )
            except Exception:
                pass

        return False, current_rank, (
            "I don't have permission to add that rank."
        )

    except discord.HTTPException:

        if current_rank:
            try:
                await member.add_roles(
                    current_rank,
                    reason="Restoring previous rank"
                )
            except Exception:
                pass

        return False, current_rank, (
            "Discord rejected the role change."
        )

    return True, current_rank, None


async def open_rank_menu(source, member, action):

    if action == "promote":

        roles = get_promote_roles(member)

        title = "⬆️ Promote Member"

        description = (
            f"Choose the new rank for **{member.display_name}**.\n\n"
            "Only ranks higher than their current rank are shown."
        )

    else:

        roles = get_demote_roles(member)

        title = "⬇️ Demote Member"

        description = (
            f"Choose the new rank for **{member.display_name}**.\n\n"
            "Only ranks lower than their current rank are shown."
        )

    if not roles:

        message = (
            "❌ No higher ranks are available."
            if action == "promote"
            else "❌ No lower ranks are available."
        )

        if isinstance(source, discord.Interaction):
            await source.response.send_message(
                message,
                ephemeral=True
            )
        else:
            await source.send(message)

        return

    current_rank = get_current_rank(member)

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Member",
        value=member.mention,
        inline=True
    )

    embed.add_field(
        name="Current rank",
        value=(
            current_rank.mention
            if current_rank
            else "No rank"
        ),
        inline=True
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    view = RolePanel(
        member,
        action,
        roles
    )

    if isinstance(source, discord.Interaction):

        await source.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )

    else:

        await source.send(
            embed=embed,
            view=view
        )


# =========================================================
# MEMBER COUNT
# =========================================================

@bot.command(name="membercount")
async def membercount_prefix(ctx):

    await ctx.send(
        f"👥 **{ctx.guild.member_count:,} members**"
    )


@bot.tree.command(
    name="membercount",
    description="Show the server member count."
)
async def membercount_slash(interaction):

    await interaction.response.send_message(
        f"👥 **{interaction.guild.member_count:,} members**"
    )


# =========================================================
# BAN
# =========================================================

class BanTargetConverter(commands.Converter):

    async def convert(self, ctx, argument):

        argument = argument.strip()

        mention_match = re.fullmatch(
            r"<@!?(\d+)>",
            argument
        )

        if mention_match:
            user_id = int(mention_match.group(1))

        elif argument.isdigit():
            user_id = int(argument)

        else:
            raise commands.BadArgument(
                "Use a member mention or a Discord user ID."
            )

        member = ctx.guild.get_member(user_id)

        if member is not None:
            return member

        return discord.Object(id=user_id)


async def get_ban_target(guild, user_id):

    member = guild.get_member(user_id)

    if member is not None:
        return member

    return discord.Object(id=user_id)


@bot.command(name="ban")
@has_permissions_or_owner(ban_members=True)
async def ban_prefix(
    ctx,
    target: BanTargetConverter,
    *,
    reason="No reason provided"
):

    target_id = target.id

    if target_id == ctx.author.id:

        await ctx.send(
            "❌ You cannot ban yourself."
        )

        return

    if isinstance(target, discord.Member):

        if target == ctx.guild.me:

            await ctx.send(
                "❌ You cannot ban the bot."
            )

            return

        if target.top_role >= ctx.guild.me.top_role:

            await ctx.send(
                "❌ I cannot ban this user because their highest "
                "role is equal to or above mine."
            )

            return

    try:

        await ctx.guild.ban(
            target,
            reason=f"{reason} | By {ctx.author}"
        )

        if isinstance(target, discord.Member):
            display_name = str(target)
        else:
            display_name = f"User ID `{target.id}`"

        await ctx.send(
            f"🔨 **{display_name}** has been banned.\n"
            f"Reason: **{reason}**"
        )

    except discord.NotFound:

        await ctx.send(
            "❌ That Discord user ID does not exist."
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to ban that user."
        )

    except discord.HTTPException as e:

        await ctx.send(
            f"❌ Discord rejected the ban: `{e}`"
        )


@bot.tree.command(
    name="ban",
    description="Ban a member or a Discord user by ID."
)
@app_commands.describe(
    member="Member currently in the server",
    user_id="Discord user ID, including users who are not in the server",
    reason="Reason for the ban"
)
@app_commands.check(app_has_permissions_or_owner(ban_members=True))
async def ban_slash(
    interaction,
    member: discord.Member | None = None,
    user_id: str | None = None,
    reason: str = "No reason provided"
):

    if member is None and user_id is None:

        await interaction.response.send_message(
            "❌ Select a member or enter a Discord user ID.",
            ephemeral=True
        )

        return

    if member is not None and user_id is not None:

        await interaction.response.send_message(
            "❌ Use either a member or a user ID, not both.",
            ephemeral=True
        )

        return

    if member is not None:

        target_id = member.id
        target = member

    else:

        if not user_id.isdigit():

            await interaction.response.send_message(
                "❌ Invalid Discord user ID.",
                ephemeral=True
            )

            return

        target_id = int(user_id)

        if target_id == interaction.user.id:

            await interaction.response.send_message(
                "❌ You cannot ban yourself.",
                ephemeral=True
            )

            return

        target = await get_ban_target(
            interaction.guild,
            target_id
        )

    if target_id == interaction.user.id:

        await interaction.response.send_message(
            "❌ You cannot ban yourself.",
            ephemeral=True
        )

        return

    if isinstance(target, discord.Member):

        if target == interaction.guild.me:

            await interaction.response.send_message(
                "❌ You cannot ban the bot.",
                ephemeral=True
            )

            return

        if target.top_role >= interaction.guild.me.top_role:

            await interaction.response.send_message(
                "❌ I cannot ban this user because their highest "
                "role is equal to or above mine.",
                ephemeral=True
            )

            return

    try:

        await interaction.guild.ban(
            target,
            reason=f"{reason} | By {interaction.user}"
        )

        if isinstance(target, discord.Member):
            display_name = str(target)
        else:
            display_name = f"User ID `{target.id}`"

        await interaction.response.send_message(
            f"🔨 **{display_name}** has been banned.\n"
            f"Reason: **{reason}**"
        )

    except discord.NotFound:

        await interaction.response.send_message(
            "❌ That Discord user ID does not exist.",
            ephemeral=True
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to ban that user.",
            ephemeral=True
        )

    except discord.HTTPException as e:

        await interaction.response.send_message(
            f"❌ Discord rejected the ban: `{e}`",
            ephemeral=True
        )


# =========================================================
# KICK
# =========================================================

@bot.command(name="kick")
@has_permissions_or_owner(kick_members=True)
async def kick_prefix(
    ctx,
    member: discord.Member,
    *,
    reason="No reason provided"
):

    if member == ctx.author:

        await ctx.send(
            "❌ You cannot kick yourself."
        )

        return

    try:

        await member.kick(
            reason=f"{reason} | By {ctx.author}"
        )

        await ctx.send(
            f"👢 **{member}** has been kicked.\n"
            f"Reason: **{reason}**"
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to kick that user."
        )


@bot.tree.command(
    name="kick",
    description="Kick a member."
)
@app_commands.describe(
    member="Member to kick",
    reason="Reason for the kick"
)
@app_commands.check(app_has_permissions_or_owner(kick_members=True))
async def kick_slash(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You cannot kick yourself.",
            ephemeral=True
        )

        return

    try:

        await member.kick(
            reason=f"{reason} | By {interaction.user}"
        )

        await interaction.response.send_message(
            f"👢 **{member}** has been kicked.\n"
            f"Reason: **{reason}**"
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to kick that user.",
            ephemeral=True
        )


# =========================================================
# UNBAN
# =========================================================

@bot.command(name="unban")
@has_permissions_or_owner(ban_members=True)
async def unban_prefix(ctx, user_id: int):

    try:

        user = await bot.fetch_user(user_id)

        await ctx.guild.unban(user)

        await ctx.send(
            f"✅ **{user}** has been unbanned."
        )

    except discord.NotFound:

        await ctx.send(
            "❌ User is not banned or does not exist."
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to unban that user."
        )


@bot.tree.command(
    name="unban",
    description="Unban a user by ID."
)
@app_commands.describe(
    user_id="Discord user ID"
)
@app_commands.check(app_has_permissions_or_owner(ban_members=True))
async def unban_slash(interaction, user_id: str):

    try:

        user = await bot.fetch_user(
            int(user_id)
        )

        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"✅ **{user}** has been unbanned."
        )

    except ValueError:

        await interaction.response.send_message(
            "❌ Invalid user ID.",
            ephemeral=True
        )

    except discord.NotFound:

        await interaction.response.send_message(
            "❌ User is not banned or does not exist.",
            ephemeral=True
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to unban that user.",
            ephemeral=True
        )


# =========================================================
# SET NICK
# =========================================================

async def change_nickname(member, nickname):

    guild = member.guild

    if guild.me is None:

        return False, "I couldn't detect my bot role."

    if member.top_role >= guild.me.top_role:

        return False, (
            "I cannot change this user's nickname because their highest "
            "role is equal to or above mine."
        )

    try:

        await member.edit(
            nick=nickname,
            reason="Nickname changed by moderation bot"
        )

        return True, None

    except discord.Forbidden:

        return False, (
            "I don't have permission to change this nickname."
        )

    except discord.HTTPException:

        return False, (
            "Discord rejected the nickname change."
        )


@bot.command(name="setnick")
@has_permissions_or_owner(manage_nicknames=True)
async def setnick_prefix(
    ctx,
    member: discord.Member,
    *,
    nickname: str
):

    # Allow names with spaces to be wrapped in straight or curly quotes.
    nickname = nickname.strip()
    if len(nickname) >= 2 and (
        (nickname[0] == nickname[-1] and nickname[0] in ('"', "'"))
        or (nickname[0] == '“' and nickname[-1] == '”')
    ):
        nickname = nickname[1:-1].strip()

    success, error = await change_nickname(
        member,
        nickname
    )

    if not success:

        await ctx.send(f"❌ {error}")
        return

    await ctx.send(
        f"✅ Changed **{member}**'s nickname to **{nickname}**."
    )


@bot.tree.command(
    name="setnick",
    description="Change a member's nickname."
)
@app_commands.describe(
    member="Member",
    nickname="New nickname"
)
@app_commands.check(app_has_permissions_or_owner(manage_nicknames=True))
async def setnick_slash(
    interaction,
    member: discord.Member,
    nickname: str
):

    success, error = await change_nickname(
        member,
        nickname
    )

    if not success:

        await interaction.response.send_message(
            f"❌ {error}",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        f"✅ Changed **{member}**'s nickname to **{nickname}**."
    )


@bot.command(name="nick")
async def nick_prefix(ctx):

    await ctx.send(
        "Use `?setnick @user nickname` to change a nickname."
    )


# =========================================================
# PURGE
# =========================================================

@bot.command(name="purge")
@has_permissions_or_owner(manage_messages=True)
async def purge_prefix(ctx, amount: int):

    if amount < 1 or amount > 100:

        await ctx.send(
            "❌ Amount must be between 1 and 100."
        )

        return

    deleted = await ctx.channel.purge(
        limit=amount + 1
    )

    msg = await ctx.send(
        f"🧹 Deleted **{len(deleted) - 1} messages**."
    )

    await asyncio_sleep(3)

    try:
        await msg.delete()
    except Exception:
        pass


@bot.tree.command(
    name="purge",
    description="Delete messages."
)
@app_commands.describe(
    amount="Number of messages to delete"
)
@app_commands.check(app_has_permissions_or_owner(manage_messages=True))
async def purge_slash(interaction, amount: int):

    if amount < 1 or amount > 100:

        await interaction.response.send_message(
            "❌ Amount must be between 1 and 100.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)} messages**."
    )


# =========================================================
# PREFIX
# =========================================================

@bot.command(name="prefix")
@has_permissions_or_owner(administrator=True)
async def prefix_prefix(ctx, new_prefix: str):

    if len(new_prefix) > 5:

        await ctx.send(
            "❌ Prefix must be 5 characters or less."
        )

        return

    set_prefix(
        ctx.guild.id,
        new_prefix
    )

    await ctx.send(
        f"✅ Prefix changed to `{new_prefix}`."
    )


@bot.tree.command(
    name="prefix",
    description="Change the server prefix."
)
@app_commands.describe(
    new_prefix="New prefix"
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def prefix_slash(
    interaction,
    new_prefix: str
):

    if len(new_prefix) > 5:

        await interaction.response.send_message(
            "❌ Prefix must be 5 characters or less.",
            ephemeral=True
        )

        return

    set_prefix(
        interaction.guild.id,
        new_prefix
    )

    await interaction.response.send_message(
        f"✅ Prefix changed to `{new_prefix}`."
    )


# =========================================================
# MESSAGE STATS
# =========================================================

def get_period_start(period):

    now = utcnow()

    if period == "today":

        return now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    if period == "week":

        monday = now - timedelta(
            days=now.weekday()
        )

        return monday.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    if period == "month":

        return now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

    return None


def get_real_messages(guild_id, user_id, period):

    with sqlite3.connect(MESSAGES_DB) as conn:

        if period == "total":

            row = conn.execute("""
                SELECT COUNT(*)
                FROM messages
                WHERE guild_id = ?
                AND user_id = ?
            """, (
                guild_id,
                user_id
            )).fetchone()

        else:

            start = get_period_start(period)

            row = conn.execute("""
                SELECT COUNT(*)
                FROM messages
                WHERE guild_id = ?
                AND user_id = ?
                AND created_at >= ?
            """, (
                guild_id,
                user_id,
                start.isoformat()
            )).fetchone()

    return row[0] if row else 0


def get_adjustment(guild_id, user_id, period):

    with sqlite3.connect(MESSAGES_DB) as conn:

        row = conn.execute("""
            SELECT amount
            FROM message_adjustments
            WHERE guild_id = ?
            AND user_id = ?
            AND period = ?
        """, (
            guild_id,
            user_id,
            period
        )).fetchone()

    return row[0] if row else 0


def get_message_count(guild_id, user_id, period):

    real = get_real_messages(
        guild_id,
        user_id,
        period
    )

    adjustment = get_adjustment(
        guild_id,
        user_id,
        period
    )

    return max(0, real + adjustment)


def set_message_count(
    guild_id,
    user_id,
    period,
    target
):

    real = get_real_messages(
        guild_id,
        user_id,
        period
    )

    adjustment = target - real

    with sqlite3.connect(MESSAGES_DB) as conn:

        conn.execute("""
            INSERT INTO message_adjustments (
                guild_id,
                user_id,
                period,
                amount,
                reference_real,
                period_start
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, period)
            DO UPDATE SET
                amount = excluded.amount,
                reference_real = excluded.reference_real,
                period_start = excluded.period_start
        """, (
            guild_id,
            user_id,
            period,
            adjustment,
            real,
            (
                get_period_start(period).isoformat()
                if period != "total"
                else None
            )
        ))

        conn.commit()


def normalize_period(period):

    aliases = {
        "today": "today",
        "day": "today",
        "d": "today",
        "week": "week",
        "weekly": "week",
        "w": "week",
        "month": "month",
        "monthly": "month",
        "m": "month",
        "total": "total",
        "year": "total",
        "all": "total"
    }

    return aliases.get(
        period.lower()
    )


def message_stats_embed(guild, member):

    today = get_message_count(
        guild.id,
        member.id,
        "today"
    )

    week = get_message_count(
        guild.id,
        member.id,
        "week"
    )

    month = get_message_count(
        guild.id,
        member.id,
        "month"
    )

    total = get_message_count(
        guild.id,
        member.id,
        "total"
    )

    embed = discord.Embed(
        title=f"📊 Message Activity — {member.display_name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Today",
        value=f"`{today:,}`",
        inline=True
    )

    embed.add_field(
        name="This Week",
        value=f"`{week:,}`",
        inline=True
    )

    embed.add_field(
        name="This Month",
        value=f"`{month:,}`",
        inline=True
    )

    embed.add_field(
        name="Total",
        value=f"`{total:,}`",
        inline=False
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    return embed


@bot.command(name="am")
async def am_prefix(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author

    await ctx.send(
        embed=message_stats_embed(
            ctx.guild,
            member
        )
    )


@bot.tree.command(
    name="am",
    description="View message activity."
)
@app_commands.describe(
    member="Member to check"
)
async def am_slash(
    interaction,
    member: discord.Member | None = None
):

    member = member or interaction.user

    await interaction.response.send_message(
        embed=message_stats_embed(
            interaction.guild,
            member
        )
    )


# =========================================================
# ASET
# =========================================================

@bot.command(name="aset")
@has_permissions_or_owner(administrator=True)
async def aset_prefix(
    ctx,
    period: str,
    amount: int,
    member: discord.Member = None
):

    member = member or ctx.author

    period = normalize_period(period)

    if period is None:

        await ctx.send(
            "❌ Period must be `today`, `week`, `month` or `total`."
        )

        return

    if amount < 0:

        await ctx.send(
            "❌ Amount cannot be negative."
        )

        return

    set_message_count(
        ctx.guild.id,
        member.id,
        period,
        amount
    )

    await ctx.send(
        f"✅ Set **{period}** messages for "
        f"**{member.display_name}** to **{amount:,}**."
    )


@bot.tree.command(
    name="aset",
    description="Set message statistics."
)
@app_commands.describe(
    period="today, week, month or total",
    amount="New amount",
    member="Member"
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def aset_slash(
    interaction,
    period: str,
    amount: int,
    member: discord.Member | None = None
):

    member = member or interaction.user

    period = normalize_period(period)

    if period is None:

        await interaction.response.send_message(
            "❌ Period must be `today`, `week`, `month` or `total`.",
            ephemeral=True
        )

        return

    if amount < 0:

        await interaction.response.send_message(
            "❌ Amount cannot be negative.",
            ephemeral=True
        )

        return

    set_message_count(
        interaction.guild.id,
        member.id,
        period,
        amount
    )

    await interaction.response.send_message(
        f"✅ Set **{period}** messages for "
        f"**{member.display_name}** to **{amount:,}**."
    )


# =========================================================
# ENABLE / DISABLE MESSAGE COUNTING
# =========================================================

@bot.command(name="aenable")
@has_permissions_or_owner(administrator=True)
async def aenable_prefix(ctx):

    set_messages_enabled(
        ctx.guild.id,
        True
    )

    await ctx.send(
        "✅ Message activity counting is now **enabled**."
    )


@bot.tree.command(
    name="aenable",
    description="Enable message activity counting."
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def aenable_slash(interaction):

    set_messages_enabled(
        interaction.guild.id,
        True
    )

    await interaction.response.send_message(
        "✅ Message activity counting is now **enabled**."
    )


@bot.command(name="adesable")
@has_permissions_or_owner(administrator=True)
async def adesable_prefix(ctx):

    set_messages_enabled(
        ctx.guild.id,
        False
    )

    await ctx.send(
        "⛔ Message activity counting is now **disabled**."
    )


@bot.tree.command(
    name="adesable",
    description="Disable message activity counting."
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def adesable_slash(interaction):

    set_messages_enabled(
        interaction.guild.id,
        False
    )

    await interaction.response.send_message(
        "⛔ Message activity counting is now **disabled**."
    )


# =========================================================
# AFK
# =========================================================

async def set_afk(source, member, reason):

    guild = member.guild

    with sqlite3.connect(AFK_DB) as conn:

        existing = conn.execute("""
            SELECT user_id
            FROM afk
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            guild.id,
            member.id
        )).fetchone()

        if existing:

            if isinstance(source, discord.Interaction):

                await source.response.send_message(
                    "❌ You are already AFK.",
                    ephemeral=True
                )

            else:

                await source.send(
                    "❌ You are already AFK."
                )

            return

        original_nick = member.nick

        conn.execute("""
            INSERT INTO afk (
                guild_id,
                user_id,
                reason,
                original_nick
            )
            VALUES (?, ?, ?, ?)
        """, (
            guild.id,
            member.id,
            reason,
            original_nick
        ))

        conn.commit()

    new_nick = f"[AFK] {member.display_name}"

    if len(new_nick) > 32:
        new_nick = new_nick[:32]

    try:

        await member.edit(
            nick=new_nick
        )

    except Exception:
        pass

    text = (
        f"💤 {member.mention} is now AFK.\n"
        f"**Reason:** {reason}"
    )

    if isinstance(source, discord.Interaction):

        await source.response.send_message(text)

    else:

        await source.send(text)


@bot.command(name="afk")
async def afk_prefix(ctx, *, reason: str):

    await set_afk(
        ctx,
        ctx.author,
        reason
    )


@bot.tree.command(
    name="afk",
    description="Set yourself as AFK."
)
@app_commands.describe(
    reason="Why you are AFK"
)
async def afk_slash(interaction, reason: str):

    await set_afk(
        interaction,
        interaction.user,
        reason
    )


class AFKMessageModal(discord.ui.Modal):

    def __init__(
        self,
        guild_id,
        afk_user_id,
        sender_id
    ):

        super().__init__(
            title="Leave a message"
        )

        self.guild_id = guild_id
        self.afk_user_id = afk_user_id
        self.sender_id = sender_id

        self.message_input = discord.ui.TextInput(
            label="Message",
            placeholder="Write your message...",
            required=True,
            max_length=1000
        )

        self.add_item(
            self.message_input
        )

    async def on_submit(self, interaction):

        with sqlite3.connect(AFK_DB) as conn:

            conn.execute("""
                INSERT INTO afk_messages (
                    guild_id,
                    afk_user_id,
                    sender_id,
                    message,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                self.guild_id,
                self.afk_user_id,
                self.sender_id,
                str(self.message_input.value),
                utcnow().isoformat()
            ))

            conn.commit()

        await interaction.response.send_message(
            "✅ Your message has been saved and will be delivered when they return.",
            ephemeral=True
        )


class AFKMessageView(discord.ui.View):

    def __init__(
        self,
        guild_id,
        afk_user_id,
        sender_id
    ):

        super().__init__(timeout=300)

        self.guild_id = guild_id
        self.afk_user_id = afk_user_id
        self.sender_id = sender_id

    @discord.ui.button(
        label="Leave a message",
        style=discord.ButtonStyle.primary
    )
    async def leave_message(
        self,
        interaction,
        button
    ):

        if interaction.user.id != self.sender_id:

            await interaction.response.send_message(
                "❌ Only the person who mentioned the AFK user can use this button.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            AFKMessageModal(
                self.guild_id,
                self.afk_user_id,
                self.sender_id
            )
        )


# =========================================================
# WARNINGS
# =========================================================

def get_warning_count(guild_id, user_id):

    with sqlite3.connect(WARNINGS_DB) as conn:

        row = conn.execute("""
            SELECT COUNT(*)
            FROM warnings
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            guild_id,
            user_id
        )).fetchone()

    return row[0] if row else 0


def get_warnings(guild_id, user_id):

    with sqlite3.connect(WARNINGS_DB) as conn:

        rows = conn.execute("""
            SELECT moderator_id, reason, created_at
            FROM warnings
            WHERE guild_id = ?
            AND user_id = ?
            ORDER BY id DESC
        """, (
            guild_id,
            user_id
        )).fetchall()

    return rows


@bot.command(name="warn")
@has_permissions_or_owner(moderate_members=True)
async def warn_prefix(
    ctx,
    member: discord.Member,
    *,
    reason="No reason provided"
):

    if member == ctx.author:

        await ctx.send(
            "❌ You cannot warn yourself."
        )

        return

    if member.bot:

        await ctx.send(
            "❌ You cannot warn a bot."
        )

        return

    with sqlite3.connect(WARNINGS_DB) as conn:

        conn.execute("""
            INSERT INTO warnings (
                guild_id,
                user_id,
                moderator_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            ctx.guild.id,
            member.id,
            ctx.author.id,
            reason,
            utcnow().isoformat()
        ))

        conn.commit()

    count = get_warning_count(
        ctx.guild.id,
        member.id
    )

    await ctx.send(
        f"⚠️ **{member}** received a warning.\n"
        f"Reason: **{reason}**\n"
        f"Warnings: **{count}/{MAX_WARNINGS}**"
    )

    if count >= MAX_WARNINGS:

        try:

            await member.timeout(
                timedelta(
                    seconds=WARNING_TIMEOUT_SECONDS
                ),
                reason="Reached maximum warnings"
            )

            await ctx.send(
                f"🔇 **{member}** has been timed out for 1 hour."
            )

        except Exception:
            pass


@bot.tree.command(
    name="warn",
    description="Warn a member."
)
@app_commands.describe(
    member="Member",
    reason="Warning reason"
)
@app_commands.check(app_has_permissions_or_owner(moderate_members=True))
async def warn_slash(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You cannot warn yourself.",
            ephemeral=True
        )

        return

    if member.bot:

        await interaction.response.send_message(
            "❌ You cannot warn a bot.",
            ephemeral=True
        )

        return

    with sqlite3.connect(WARNINGS_DB) as conn:

        conn.execute("""
            INSERT INTO warnings (
                guild_id,
                user_id,
                moderator_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            interaction.guild.id,
            member.id,
            interaction.user.id,
            reason,
            utcnow().isoformat()
        ))

        conn.commit()

    count = get_warning_count(
        interaction.guild.id,
        member.id
    )

    await interaction.response.send_message(
        f"⚠️ **{member}** received a warning.\n"
        f"Reason: **{reason}**\n"
        f"Warnings: **{count}/{MAX_WARNINGS}**"
    )

    if count >= MAX_WARNINGS:

        try:

            await member.timeout(
                timedelta(
                    seconds=WARNING_TIMEOUT_SECONDS
                ),
                reason="Reached maximum warnings"
            )

            await interaction.followup.send(
                f"🔇 **{member}** has been timed out for 1 hour."
            )

        except Exception:
            pass


# =========================================================
# WARNINGS LIST
# =========================================================

@bot.command(name="warnings")
async def warnings_prefix(
    ctx,
    member: discord.Member
):

    rows = get_warnings(
        ctx.guild.id,
        member.id
    )

    if not rows:

        await ctx.send(
            f"✅ **{member}** has no warnings."
        )

        return

    embed = discord.Embed(
        title=f"⚠️ Warnings — {member}",
        color=discord.Color.orange()
    )

    for index, (
        moderator_id,
        reason,
        created_at
    ) in enumerate(rows[:25], 1):

        moderator = ctx.guild.get_member(
            moderator_id
        )

        moderator_name = (
            moderator.display_name
            if moderator
            else str(moderator_id)
        )

        embed.add_field(
            name=f"Warning #{index}",
            value=(
                f"**Reason:** {reason}\n"
                f"**Moderator:** {moderator_name}\n"
                f"**Date:** {created_at}"
            ),
            inline=False
        )

    await ctx.send(
        embed=embed
    )


@bot.tree.command(
    name="warnings",
    description="View a member's warnings."
)
@app_commands.describe(
    member="Member"
)
async def warnings_slash(
    interaction,
    member: discord.Member
):

    rows = get_warnings(
        interaction.guild.id,
        member.id
    )

    if not rows:

        await interaction.response.send_message(
            f"✅ **{member}** has no warnings."
        )

        return

    embed = discord.Embed(
        title=f"⚠️ Warnings — {member}",
        color=discord.Color.orange()
    )

    for index, (
        moderator_id,
        reason,
        created_at
    ) in enumerate(rows[:25], 1):

        moderator = interaction.guild.get_member(
            moderator_id
        )

        moderator_name = (
            moderator.display_name
            if moderator
            else str(moderator_id)
        )

        embed.add_field(
            name=f"Warning #{index}",
            value=(
                f"**Reason:** {reason}\n"
                f"**Moderator:** {moderator_name}\n"
                f"**Date:** {created_at}"
            ),
            inline=False
        )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# CLEAR WARNINGS
# =========================================================

@bot.command(name="clearwarns")
@has_permissions_or_owner(moderate_members=True)
async def clearwarns_prefix(
    ctx,
    member: discord.Member
):

    with sqlite3.connect(WARNINGS_DB) as conn:

        conn.execute("""
            DELETE FROM warnings
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            ctx.guild.id,
            member.id
        ))

        conn.commit()

    await ctx.send(
        f"✅ Cleared all warnings for **{member}**."
    )


@bot.tree.command(
    name="clearwarns",
    description="Clear all warnings from a member."
)
@app_commands.describe(
    member="Member"
)
@app_commands.check(app_has_permissions_or_owner(moderate_members=True))
async def clearwarns_slash(
    interaction,
    member: discord.Member
):

    with sqlite3.connect(WARNINGS_DB) as conn:

        conn.execute("""
            DELETE FROM warnings
            WHERE guild_id = ?
            AND user_id = ?
        """, (
            interaction.guild.id,
            member.id
        ))

        conn.commit()

    await interaction.response.send_message(
        f"✅ Cleared all warnings for **{member}**."
    )


# =========================================================
# MUTE
# =========================================================

def parse_duration(duration):

    match = re.fullmatch(
        r"(\d+)(s|m|h|d|w)",
        duration.lower()
    )

    if not match:
        return None

    amount = int(
        match.group(1)
    )

    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800
    }

    seconds = amount * multipliers[unit]

    if seconds > MAX_MUTE_SECONDS:
        return None

    return seconds


@bot.command(name="mute")
@has_permissions_or_owner(moderate_members=True)
async def mute_prefix(
    ctx,
    member: discord.Member,
    duration: str,
    *,
    reason="No reason provided"
):

    if member == ctx.author:

        await ctx.send(
            "❌ You cannot mute yourself."
        )

        return

    seconds = parse_duration(duration)

    if seconds is None:

        await ctx.send(
            "❌ Invalid duration. Examples: `10s`, `10m`, `1h`, `1d`, `1w`.\n"
            "Maximum: 28 days."
        )

        return

    try:

        await member.timeout(
            timedelta(seconds=seconds),
            reason=reason
        )

        await ctx.send(
            f"🔇 **{member}** has been muted for "
            f"**{duration}**.\n"
            f"Reason: **{reason}**"
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to mute that user."
        )


@bot.tree.command(
    name="mute",
    description="Mute a member."
)
@app_commands.describe(
    member="Member",
    duration="Examples: 10m, 1h, 1d",
    reason="Reason"
)
@app_commands.check(app_has_permissions_or_owner(moderate_members=True))
async def mute_slash(
    interaction,
    member: discord.Member,
    duration: str,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You cannot mute yourself.",
            ephemeral=True
        )

        return

    seconds = parse_duration(duration)

    if seconds is None:

        await interaction.response.send_message(
            "❌ Invalid duration. Maximum is 28 days.",
            ephemeral=True
        )

        return

    try:

        await member.timeout(
            timedelta(seconds=seconds),
            reason=reason
        )

        await interaction.response.send_message(
            f"🔇 **{member}** has been muted for "
            f"**{duration}**.\n"
            f"Reason: **{reason}**"
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to mute that user.",
            ephemeral=True
        )


# =========================================================
# UNMUTE
# =========================================================

@bot.command(name="unmute")
@has_permissions_or_owner(moderate_members=True)
async def unmute_prefix(
    ctx,
    member: discord.Member
):

    try:

        await member.timeout(
            None,
            reason=f"Unmuted by {ctx.author}"
        )

        await ctx.send(
            f"🔊 **{member}** has been unmuted."
        )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to unmute that user."
        )


@bot.tree.command(
    name="unmute",
    description="Remove a timeout from a member."
)
@app_commands.describe(
    member="Member"
)
@app_commands.check(app_has_permissions_or_owner(moderate_members=True))
async def unmute_slash(
    interaction,
    member: discord.Member
):

    try:

        await member.timeout(
            None,
            reason=f"Unmuted by {interaction.user}"
        )

        await interaction.response.send_message(
            f"🔊 **{member}** has been unmuted."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to unmute that user.",
            ephemeral=True
        )


# =========================================================
# PROMOTE
# =========================================================

@bot.command(name="promote")
@has_permissions_or_owner(manage_roles=True)
async def promote_prefix(
    ctx,
    member: discord.Member
):

    await open_rank_menu(
        ctx,
        member,
        "promote"
    )


@bot.tree.command(
    name="promote",
    description="Promote a member."
)
@app_commands.describe(
    member="Member to promote"
)
@app_commands.check(app_has_permissions_or_owner(manage_roles=True))
async def promote_slash(
    interaction,
    member: discord.Member
):

    await open_rank_menu(
        interaction,
        member,
        "promote"
    )


# =========================================================
# DEMOTE
# =========================================================

@bot.command(name="demote")
@has_permissions_or_owner(manage_roles=True)
async def demote_prefix(
    ctx,
    member: discord.Member
):

    await open_rank_menu(
        ctx,
        member,
        "demote"
    )


@bot.tree.command(
    name="demote",
    description="Demote a member."
)
@app_commands.describe(
    member="Member to demote"
)
@app_commands.check(app_has_permissions_or_owner(manage_roles=True))
async def demote_slash(
    interaction,
    member: discord.Member
):

    await open_rank_menu(
        interaction,
        member,
        "demote"
    )


# =========================================================
# ROLE
# =========================================================

@bot.command(name="role")
@has_permissions_or_owner(manage_roles=True)
async def role_prefix(
    ctx,
    action: str,
    member: discord.Member,
    role: discord.Role
):

    action = action.lower()

    if action not in ("add", "remove"):

        await ctx.send(
            "❌ Use `?role add @user @role` or "
            "`?role remove @user @role`."
        )

        return

    if role >= ctx.guild.me.top_role:

        await ctx.send(
            "❌ I cannot manage that role."
        )

        return

    try:

        if action == "add":

            await member.add_roles(
                role,
                reason=f"Role added by {ctx.author}"
            )

            await ctx.send(
                f"✅ Added {role.mention} to {member.mention}.",
                allowed_mentions=discord.AllowedMentions.none()
            )

        else:

            await member.remove_roles(
                role,
                reason=f"Role removed by {ctx.author}"
            )

            await ctx.send(
                f"✅ Removed {role.mention} from {member.mention}.",
                allowed_mentions=discord.AllowedMentions.none()
            )

    except discord.Forbidden:

        await ctx.send(
            "❌ I don't have permission to manage that role."
        )


# =========================================================
# SLASH ROLE GROUP
# =========================================================

role_group = app_commands.Group(
    name="role",
    description="Manage member roles."
)


@role_group.command(
    name="add",
    description="Add a role to a member."
)
@app_commands.describe(
    member="Member",
    role="Role"
)
@app_commands.check(app_has_permissions_or_owner(manage_roles=True))
async def role_add_slash(
    interaction,
    member: discord.Member,
    role: discord.Role
):

    if role >= interaction.guild.me.top_role:

        await interaction.response.send_message(
            "❌ I cannot manage that role.",
            ephemeral=True
        )

        return

    try:

        await member.add_roles(
            role,
            reason=f"Role added by {interaction.user}"
        )

        await interaction.response.send_message(
            f"✅ Added {role.mention} to {member.mention}.",
            allowed_mentions=discord.AllowedMentions.none()
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to manage that role.",
            ephemeral=True
        )


@role_group.command(
    name="remove",
    description="Remove a role from a member."
)
@app_commands.describe(
    member="Member",
    role="Role"
)
@app_commands.check(app_has_permissions_or_owner(manage_roles=True))
async def role_remove_slash(
    interaction,
    member: discord.Member,
    role: discord.Role
):

    if role >= interaction.guild.me.top_role:

        await interaction.response.send_message(
            "❌ I cannot manage that role.",
            ephemeral=True
        )

        return

    try:

        await member.remove_roles(
            role,
            reason=f"Role removed by {interaction.user}"
        )

        await interaction.response.send_message(
            f"✅ Removed {role.mention} from {member.mention}.",
            allowed_mentions=discord.AllowedMentions.none()
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I don't have permission to manage that role.",
            ephemeral=True
        )


bot.tree.add_command(role_group)


# =========================================================
# LOCK / UNLOCK CHANNEL
# =========================================================

async def set_channel_lock(channel, locked, reason):

    default_role = channel.guild.default_role
    overwrite = channel.overwrites_for(default_role)
    overwrite.send_messages = False if locked else None

    await channel.set_permissions(
        default_role,
        overwrite=overwrite,
        reason=reason
    )


@bot.command(name="lock")
@has_permissions_or_owner(manage_channels=True)
async def lock_prefix(ctx, *, reason="Channel locked by a moderator"):

    try:
        await set_channel_lock(
            ctx.channel,
            True,
            f"{reason} | By {ctx.author}"
        )
        await ctx.send("🔒 This channel has been locked.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to change this channel's permissions.")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Discord rejected the change: `{e}`")


@bot.tree.command(name="lock", description="Lock a channel so members cannot send messages.")
@app_commands.describe(channel="Channel to lock", reason="Reason for locking")
@app_commands.check(app_has_permissions_or_owner(manage_channels=True))
async def lock_slash(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
    reason: str = "Channel locked by a moderator"
):

    channel = channel or interaction.channel
    try:
        await set_channel_lock(
            channel,
            True,
            f"{reason} | By {interaction.user}"
        )
        await interaction.response.send_message(
            f"🔒 {channel.mention} has been locked."
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change this channel's permissions.",
            ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Discord rejected the change: `{e}`",
            ephemeral=True
        )


@bot.command(name="unlock")
@has_permissions_or_owner(manage_channels=True)
async def unlock_prefix(ctx, *, reason="Channel unlocked by a moderator"):

    try:
        await set_channel_lock(
            ctx.channel,
            False,
            f"{reason} | By {ctx.author}"
        )
        await ctx.send("🔓 This channel has been unlocked.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to change this channel's permissions.")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Discord rejected the change: `{e}`")


@bot.tree.command(name="unlock", description="Unlock a channel so members can send messages again.")
@app_commands.describe(channel="Channel to unlock", reason="Reason for unlocking")
@app_commands.check(app_has_permissions_or_owner(manage_channels=True))
async def unlock_slash(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
    reason: str = "Channel unlocked by a moderator"
):

    channel = channel or interaction.channel
    try:
        await set_channel_lock(
            channel,
            False,
            f"{reason} | By {interaction.user}"
        )
        await interaction.response.send_message(
            f"🔓 {channel.mention} has been unlocked."
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change this channel's permissions.",
            ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Discord rejected the change: `{e}`",
            ephemeral=True
        )


# =========================================================
# SLOWMODE
# =========================================================

@bot.command(name="slowmode")
@has_permissions_or_owner(manage_channels=True)
async def slowmode_prefix(ctx, seconds: int):

    if seconds < 0 or seconds > 21600:
        await ctx.send("❌ Slowmode must be between 0 and 21600 seconds (6 hours).")
        return

    try:
        await ctx.channel.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode set by {ctx.author}"
        )
        if seconds == 0:
            await ctx.send("✅ Slowmode has been disabled.")
        else:
            await ctx.send(f"🐢 Slowmode set to **{seconds} seconds**.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to change this channel.")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Discord rejected the change: `{e}`")


@bot.tree.command(name="slowmode", description="Set the channel slowmode delay in seconds.")
@app_commands.describe(seconds="Delay in seconds (0 to disable, maximum 21600)", channel="Channel to configure")
@app_commands.check(app_has_permissions_or_owner(manage_channels=True))
async def slowmode_slash(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600],
    channel: discord.TextChannel | None = None
):

    channel = channel or interaction.channel
    try:
        await channel.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode set by {interaction.user}"
        )
        if seconds == 0:
            result = f"✅ Slowmode disabled in {channel.mention}."
        else:
            result = f"🐢 Slowmode in {channel.mention} set to **{seconds} seconds**."
        await interaction.response.send_message(result)
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change this channel.",
            ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Discord rejected the change: `{e}`",
            ephemeral=True
        )


# =========================================================
# AUTOROLE
# =========================================================

def get_autorole(guild_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:
        row = conn.execute(
            "SELECT role_id FROM autorole_settings WHERE guild_id = ?",
            (guild_id,)
        ).fetchone()
    return row[0] if row else None


def set_autorole(guild_id, role_id):

    with sqlite3.connect(WELCOME_LEAVE_DB) as conn:
        if role_id is None:
            conn.execute(
                "DELETE FROM autorole_settings WHERE guild_id = ?",
                (guild_id,)
            )
        else:
            conn.execute("""
                INSERT INTO autorole_settings (guild_id, role_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET role_id = excluded.role_id
            """, (guild_id, role_id))
        conn.commit()


@bot.command(name="autorole")
@has_permissions_or_owner(administrator=True)
async def autorole_prefix(ctx, *, role_input: str = None):

    if role_input is None:
        role_id = get_autorole(ctx.guild.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role:
            await ctx.send(f"🤖 Current autorole: {role.mention}. Use `?autorole @role` to change it or `?autorole off` to disable it.")
        else:
            await ctx.send("ℹ️ Autorole is disabled. Use `?autorole @role` to configure it.")
        return

    if role_input.lower().strip() in {"off", "disable", "none", "remove"}:
        set_autorole(ctx.guild.id, None)
        await ctx.send("✅ Autorole has been disabled.")
        return

    role = None
    match = re.fullmatch(r"<@&?(\d+)>", role_input.strip())
    if match:
        role = ctx.guild.get_role(int(match.group(1)))
    elif role_input.strip().isdigit():
        role = ctx.guild.get_role(int(role_input.strip()))
    else:
        role = discord.utils.get(ctx.guild.roles, name=role_input.strip())

    if role is None:
        await ctx.send("❌ Role not found. Mention a role, enter its ID, or use its exact name.")
        return

    if role.is_default() or role.managed:
        await ctx.send("❌ That role cannot be assigned automatically.")
        return

    if ctx.guild.me and role >= ctx.guild.me.top_role:
        await ctx.send("❌ Put the bot's highest role above the autorole first.")
        return

    set_autorole(ctx.guild.id, role.id)
    await ctx.send(f"✅ Autorole set to {role.mention}. New members will receive this role.")


@bot.tree.command(name="autorole", description="Set, view, or disable the role given to new members.")
@app_commands.describe(role="Role to give new members; leave empty to view current setting")
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def autorole_slash(
    interaction: discord.Interaction,
    role: discord.Role | None = None
):

    if role is None:
        role_id = get_autorole(interaction.guild.id)
        current_role = interaction.guild.get_role(role_id) if role_id else None
        if current_role:
            await interaction.response.send_message(
                f"🤖 Current autorole: {current_role.mention}. To disable it, use `?autorole off`.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "ℹ️ Autorole is disabled. Choose a role with `/autorole role`.",
                ephemeral=True
            )
        return

    if role.is_default() or role.managed:
        await interaction.response.send_message(
            "❌ That role cannot be assigned automatically.",
            ephemeral=True
        )
        return

    if interaction.guild.me and role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "❌ Put the bot's highest role above the autorole first.",
            ephemeral=True
        )
        return

    set_autorole(interaction.guild.id, role.id)
    await interaction.response.send_message(
        f"✅ Autorole set to {role.mention}. New members will receive this role. To disable it, use `?autorole off`.",
        ephemeral=True
    )


# =========================================================
# HELP
# =========================================================

def _format_help_commands(commands_list, prefix=""):
    """Format registered commands dynamically so new commands appear in help."""
    names = sorted({command.qualified_name for command in commands_list if getattr(command, "qualified_name", None)})
    if not names:
        return "No commands registered."
    return "\n".join(f"`{prefix}{name}`" for name in names)


def build_help_embed(prefix):
    embed = discord.Embed(
        title="📚 Moderation Bot — Help",
        description=(
            f"All registered commands are listed automatically.\n"
            f"Use prefix commands with `{prefix}` or use slash commands (`/`).\n"
            f"Example: `{prefix}lock` or `/lock`."
        ),
        color=discord.Color.blurple()
    )

    prefix_commands = list(bot.walk_commands())
    slash_commands = list(bot.tree.walk_commands())

    prefix_text = _format_help_commands(prefix_commands, prefix)
    slash_text = _format_help_commands(slash_commands, "/")

    # Discord embed field values are limited to 1024 characters.
    def add_chunked_fields(title, text_value):
        lines = text_value.splitlines()
        chunk = []
        length = 0
        part = 1
        for line in lines:
            extra = len(line) + (1 if chunk else 0)
            if length + extra > 1000 and chunk:
                field_name = title if part == 1 else f"{title} (continued {part})"
                embed.add_field(name=field_name, value="\n".join(chunk), inline=False)
                part += 1
                chunk = []
                length = 0
            chunk.append(line)
            length += len(line) + (1 if len(chunk) > 1 else 0)
        if chunk:
            field_name = title if part == 1 else f"{title} (continued {part})"
            embed.add_field(name=field_name, value="\n".join(chunk), inline=False)

    add_chunked_fields("⌨️ Prefix commands", prefix_text)
    add_chunked_fields("⚡ Slash commands", slash_text)
    embed.set_footer(text="The command list updates automatically when commands are registered. Some commands require permissions.")
    return embed


@bot.command(name="help")
async def help_prefix(ctx):

    await ctx.send(embed=build_help_embed(get_prefix(ctx.guild.id)))


@bot.tree.command(name="help", description="Show the bot's important commands.")
async def help_slash(interaction: discord.Interaction):

    await interaction.response.send_message(
        embed=build_help_embed(get_prefix(interaction.guild.id)),
        ephemeral=True
    )


# =========================================================
# WELCOME SETUP
# =========================================================

@bot.tree.command(
    name="welcomesetup",
    description="Set the channel for welcome messages."
)
@app_commands.describe(
    channel="Channel where welcome messages will be sent"
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def welcomesetup_slash(
    interaction,
    channel: discord.TextChannel
):

    set_welcome_channel(
        interaction.guild.id,
        channel.id
    )

    await interaction.response.send_message(
        f"✅ Welcome channel has been set to {channel.mention}."
    )


# =========================================================
# LEAVE SETUP
# =========================================================

@bot.tree.command(
    name="leavesetup",
    description="Set the channel for leave messages."
)
@app_commands.describe(
    channel="Channel where leave messages will be sent"
)
@app_commands.check(app_has_permissions_or_owner(administrator=True))
async def leavesetup_slash(
    interaction,
    channel: discord.TextChannel
):

    set_leave_channel(
        interaction.guild.id,
        channel.id
    )

    await interaction.response.send_message(
        f"✅ Leave channel has been set to {channel.mention}."
    )


# =========================================================
# MEMBER JOIN
# =========================================================

@bot.event
async def on_member_join(member):

    autorole_id = get_autorole(member.guild.id)
    autorole = member.guild.get_role(autorole_id) if autorole_id else None

    if autorole is not None:
        try:
            if member.guild.me and autorole < member.guild.me.top_role:
                await member.add_roles(
                    autorole,
                    reason="Automatic role for new member"
                )
        except discord.Forbidden:
            print(f"❌ I cannot assign autorole {autorole.name} in {member.guild.name}.")
        except discord.HTTPException as e:
            print(f"❌ Autorole error: {e}")

    channel_id = get_welcome_channel(
        member.guild.id
    )

    if not channel_id:
        return

    channel = member.guild.get_channel(
        channel_id
    )

    if channel is None:
        return

    member_count = member.guild.member_count

    try:

        await channel.send(
            f"{member.mention} "
            f"Thx for joining this server, **{member.guild.name}!** "
            f"You make us **{member_count} members.**"
        )

    except discord.Forbidden:

        print(
            f"❌ I cannot send welcome messages in #{channel.name} "
            f"on {member.guild.name}."
        )

    except discord.HTTPException as e:

        print(
            f"❌ Welcome message error: {e}"
        )


# =========================================================
# MEMBER LEAVE
# =========================================================

@bot.event
async def on_member_remove(member):

    channel_id = get_leave_channel(
        member.guild.id
    )

    if not channel_id:
        return

    channel = member.guild.get_channel(
        channel_id
    )

    if channel is None:
        return

    member_count = member.guild.member_count

    try:

        await channel.send(
            f"{member.mention} "
            f"See you, why you leave us? "
            f"You make us **{member_count} members.**"
        )

    except discord.Forbidden:

        print(
            f"❌ I cannot send leave messages in #{channel.name} "
            f"on {member.guild.name}."
        )

    except discord.HTTPException as e:

        print(
            f"❌ Leave message error: {e}"
        )


# =========================================================
# ON MESSAGE
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # Process prefix commands immediately so an error in AFK/statistics
    # handling below cannot prevent commands such as ?ban or ?kick.
    await bot.process_commands(message)

    # The message that invokes ?afk must not immediately count as the
    # user's return. Check the parsed command and skip AFK-return handling.
    try:
        parsed_context = await bot.get_context(message)
        if parsed_context.valid and parsed_context.command is not None:
            if parsed_context.command.qualified_name == "afk":
                return
    except Exception as error:
        print(f"AFK command detection error: {error}")

    if message.guild:

        with sqlite3.connect(AFK_DB) as conn:

            afk_row = conn.execute("""
                SELECT reason, original_nick
                FROM afk
                WHERE guild_id = ?
                AND user_id = ?
            """, (
                message.guild.id,
                message.author.id
            )).fetchone()

        if afk_row:

            reason, original_nick = afk_row

            with sqlite3.connect(AFK_DB) as conn:

                conn.execute("""
                    DELETE FROM afk
                    WHERE guild_id = ?
                    AND user_id = ?
                """, (
                    message.guild.id,
                    message.author.id
                ))

                conn.commit()

            try:

                await message.author.edit(
                    nick=original_nick
                )

            except Exception:
                pass

            response = await message.channel.send(
                f"👋 {message.author.mention}, "
                f"you are no longer AFK."
            )

            await asyncio_sleep(2)

            try:
                await response.delete()
            except Exception:
                pass

            with sqlite3.connect(AFK_DB) as conn:

                saved_messages = conn.execute("""
                    SELECT sender_id, message, created_at
                    FROM afk_messages
                    WHERE guild_id = ?
                    AND afk_user_id = ?
                    ORDER BY id ASC
                """, (
                    message.guild.id,
                    message.author.id
                )).fetchall()

                conn.execute("""
                    DELETE FROM afk_messages
                    WHERE guild_id = ?
                    AND afk_user_id = ?
                """, (
                    message.guild.id,
                    message.author.id
                ))

                conn.commit()

            if saved_messages:

                text = "📨 **Messages while you were AFK:**\n\n"

                for (
                    sender_id,
                    saved_text,
                    created_at
                ) in saved_messages:

                    sender = message.guild.get_member(
                        sender_id
                    )

                    sender_name = (
                        sender.display_name
                        if sender
                        else "Unknown user"
                    )

                    text += (
                        f"**{sender_name}:** "
                        f"{saved_text}\n"
                    )

                try:

                    await message.author.send(
                        text[:1900]
                    )

                except Exception:
                    pass

        if messages_enabled(message.guild.id):

            with sqlite3.connect(MESSAGES_DB) as conn:

                conn.execute("""
                    INSERT INTO messages (
                        guild_id,
                        user_id,
                        channel_id,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    message.guild.id,
                    message.author.id,
                    message.channel.id,
                    utcnow().isoformat()
                ))

                conn.commit()

        for mentioned in message.mentions:

            if mentioned.bot:
                continue

            with sqlite3.connect(AFK_DB) as conn:

                afk_row = conn.execute("""
                    SELECT reason
                    FROM afk
                    WHERE guild_id = ?
                    AND user_id = ?
                """, (
                    message.guild.id,
                    mentioned.id
                )).fetchone()

            if afk_row:

                reason = afk_row[0]

                view = AFKMessageView(
                    message.guild.id,
                    mentioned.id,
                    message.author.id
                )

                await message.channel.send(
                    f"💤 **{mentioned.display_name} is AFK.**\n"
                    f"**Reason:** {reason}",
                    view=view
                )

                break

# =========================================================
# ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    if isinstance(
        error,
        commands.MissingPermissions
    ):

        await ctx.send(
            "❌ You don't have permission to use this command."
        )

        return

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):

        await ctx.send(
            "❌ You're missing a required argument."
        )

        return

    if isinstance(
        error,
        commands.MemberNotFound
    ):

        await ctx.send(
            "❌ Member not found."
        )

        return

    if isinstance(
        error,
        commands.RoleNotFound
    ):

        await ctx.send(
            "❌ Role not found."
        )

        return

    if isinstance(
        error,
        commands.BadArgument
    ):

        await ctx.send(
            "❌ Invalid member or Discord user ID."
        )

        return

    print(
        f"Command error in {ctx.command}: {error}"
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print("=" * 55)

    print(
        f"🤖 Logged in as: {bot.user}"
    )

    print(
        f"🆔 Bot ID: {bot.user.id}"
    )

    print(
        f"🏠 Servers: {len(bot.guilds)}"
    )

    print(
        "✅ Prefix system loaded"
    )

    print(
        "✅ Message activity loaded"
    )

    print(
        "✅ AFK system loaded"
    )

    print(
        "✅ Warning system loaded"
    )

    print(
        "✅ Mute system loaded"
    )

    print(
        "✅ Automatic rank detection loaded"
    )

    print(
        "✅ OLD Promote/Demote menu loaded"
    )

    print(
        "✅ Role management loaded"
    )

    print(
        "✅ Welcome system loaded"
    )

    print(
        "✅ Leave system loaded"
    )

    print(
        "✅ Lock / Unlock loaded"
    )

    print(
        "✅ Slowmode loaded"
    )

    print(
        "✅ Autorole loaded"
    )

    print(
        "✅ Help command loaded"
    )

    print(
        "🚀 Bot is ready!"
    )

    print("=" * 55)



# =========================================================
# SAY (OWNER ONLY)
# =========================================================

@bot.tree.command(
    name="say",
    description="Make the bot send a message (owner only)."
)
@app_commands.describe(message="The exact text the bot should send")
async def say_slash(interaction: discord.Interaction, message: str):
    # Only the configured owner can use this command.
    if interaction.user.id != OWNER_USER_ID:
        await interaction.response.send_message(
            "❌ Only the bot owner can use this command.",
            ephemeral=True
        )
        return

    if interaction.channel is None:
        await interaction.response.send_message(
            "❌ I can't send a message in this channel.",
            ephemeral=True
        )
        return

    # Avoid accidentally pinging everyone or roles when echoing arbitrary text.
    await interaction.channel.send(
        message,
        allowed_mentions=discord.AllowedMentions.none()
    )
    await interaction.response.send_message("✅ Message sent.", ephemeral=True)



# =========================================================
# ROLES (UI WITH VISIBLE @ MENTIONS, WITHOUT PINGING)
# =========================================================

class RolesPaginationView(discord.ui.View):
    def __init__(self, guild, roles, page=0):
        super().__init__(timeout=180)
        self.guild = guild
        self.roles = roles
        self.page = page
        self.page_size = 10
        self.message = None
        self.update_buttons()

    def total_pages(self):
        return max(1, (len(self.roles) + self.page_size - 1) // self.page_size)

    def make_embed(self):
        start = self.page * self.page_size
        page_roles = self.roles[start:start + self.page_size]
        description = "\\n".join(
            f"**{start + i + 1}.** {role.mention}"
            for i, role in enumerate(page_roles)
        )
        embed = discord.Embed(
            title=f"🛡️ Server Roles — {self.guild.name}",
            description=description or "No roles found.",
            color=discord.Color.blurple()
        )
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.total_pages()} • {len(self.roles)} roles"
        )
        return embed

    def update_buttons(self):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages() - 1

    async def refresh(self, interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="Previous", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages() - 1, self.page + 1)
        await self.refresh(interaction)


def build_roles_ui(guild):
    roles = [role for role in guild.roles if role != guild.default_role]
    roles.sort(key=lambda role: role.position, reverse=True)
    view = RolesPaginationView(guild, roles)
    return view.make_embed(), view


@bot.command(name="roles")
async def roles_prefix(ctx):
    if ctx.guild is None:
        await ctx.send("❌ This command can only be used in a server.")
        return

    embed, view = build_roles_ui(ctx.guild)
    await ctx.send(
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions.none()
    )


@bot.tree.command(
    name="roles",
    description="Show server roles with a paginated interface, without pinging them."
)
async def roles_slash(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )
        return

    embed, view = build_roles_ui(interaction.guild)
    await interaction.response.send_message(
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions.none()
    )


# =========================================================
# START
# =========================================================

bot.run(TOKEN)