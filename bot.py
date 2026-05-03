import json
import os
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

PREFIX = "."
DATA_DIR = Path("data")
PERMS_FILE = DATA_DIR / "permissions.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
OWNERS_FILE = DATA_DIR / "owners.json"

DEFAULT_EMBED_COLOR = 0x5865F2
COLOR_NAMES = {
    "bleu": 0x5865F2,
    "blue": 0x5865F2,
    "rose": 0xFF4FA3,
    "pink": 0xFF4FA3,
    "noir": 0x000001,
    "black": 0x000001,
    "rouge": 0xED4245,
    "red": 0xED4245,
    "vert": 0x57F287,
    "green": 0x57F287,
    "jaune": 0xFEE75C,
    "yellow": 0xFEE75C,
    "violet": 0x9B59B6,
    "purple": 0x9B59B6,
    "orange": 0xE67E22,
    "blanc": 0xFFFFFF,
    "white": 0xFFFFFF,
}

MANAGED_PERMISSIONS = {
    "ban",
    "kick",
    "clear",
    "addrole",
    "delrole",
    "unban",
    "setperm",
    "unsetperm",
    "help",
    "derank",
}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
app_owner_ids: set[int] = set()


def load_permissions() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not PERMS_FILE.exists():
        PERMS_FILE.write_text("{}", encoding="utf-8")
        return {}

    try:
        return json.loads(PERMS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_permissions(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PERMS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


permissions_data = load_permissions()


def load_settings() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text("{}", encoding="utf-8")
        return {}

    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_settings(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


settings_data = load_settings()


def load_owners() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not OWNERS_FILE.exists():
        OWNERS_FILE.write_text("{}", encoding="utf-8")
        return {}

    try:
        return json.loads(OWNERS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_owners(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OWNERS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


owners_data = load_owners()


def guild_key(guild_id: int) -> str:
    return str(guild_id)


def role_key(role_id: int) -> str:
    return str(role_id)


def get_guild_permissions(guild_id: int) -> dict:
    return permissions_data.setdefault(guild_key(guild_id), {})


def get_guild_settings(guild_id: int) -> dict:
    return settings_data.setdefault(guild_key(guild_id), {})


def get_guild_owners(guild_id: int) -> list[str]:
    return owners_data.setdefault(guild_key(guild_id), [])


def is_bot_owner(member: discord.Member) -> bool:
    return member.id in app_owner_ids or str(member.id) in get_guild_owners(member.guild.id)


def get_embed_color(guild: discord.Guild | None) -> discord.Color:
    if not guild:
        return discord.Color(DEFAULT_EMBED_COLOR)

    color = get_guild_settings(guild.id).get("embed_color", DEFAULT_EMBED_COLOR)
    return discord.Color(int(color))


def get_global_settings() -> dict:
    return settings_data.setdefault("_global", {})


async def apply_saved_presence() -> None:
    activity_settings = get_global_settings().get("activity", {})
    if activity_settings.get("type") == "streaming":
        await bot.change_presence(
            activity=discord.Streaming(
                name=activity_settings.get("name", "En direct"),
                url=activity_settings.get("url", "https://www.twitch.tv/discord"),
            )
        )
        return

    await bot.change_presence(activity=None)


def parse_color(value: str) -> int | None:
    value = value.strip().lower()

    if value in COLOR_NAMES:
        return COLOR_NAMES[value]

    if value.startswith("#"):
        value = value[1:]
    elif value.startswith("0x"):
        value = value[2:]

    if len(value) == 6 and all(char in "0123456789abcdef" for char in value):
        return int(value, 16)

    return None


async def find_or_create_text_channel(guild: discord.Guild, name: str) -> discord.TextChannel:
    existing = discord.utils.get(guild.text_channels, name=name)
    if existing:
        return existing

    return await guild.create_text_channel(name=name)


def get_log_channel(guild: discord.Guild, log_name: str) -> discord.TextChannel | None:
    channel_id = get_guild_settings(guild.id).get("logs", {}).get(log_name)
    if not channel_id:
        return None

    channel = guild.get_channel(int(channel_id))
    if isinstance(channel, discord.TextChannel):
        return channel

    return None


async def send_action_log(
    guild: discord.Guild,
    log_name: str,
    title: str,
    lines: list[str],
) -> None:
    channel = get_log_channel(guild, log_name)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=get_embed_color(guild),
    )
    await channel.send(embed=embed)


def role_has_permission(guild_id: int, role_id: int, permission: str) -> bool:
    guild_permissions = get_guild_permissions(guild_id)
    return permission in guild_permissions.get(role_key(role_id), [])


def member_has_permission(member: discord.Member, permission: str) -> bool:
    if is_bot_owner(member):
        return True

    return any(role_has_permission(member.guild.id, role.id, permission) for role in member.roles)


def require_bot_permission(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage("Cette commande doit etre utilisee dans un serveur.")

        if member_has_permission(ctx.author, permission):
            return True

        raise commands.CheckFailure(f"Tu n'as pas la permission `{permission}`.")

    return commands.check(predicate)


def require_admin_or_bot_permission(permission: str):
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage("Cette commande doit etre utilisee dans un serveur.")

        if is_bot_owner(ctx.author) or member_has_permission(ctx.author, permission):
            return True

        raise commands.CheckFailure(f"Tu n'as pas la permission `{permission}`.")

    return commands.check(predicate)


def require_admin_or_owner():
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage("Cette commande doit etre utilisee dans un serveur.")

        if is_bot_owner(ctx.author):
            return True

        raise commands.CheckFailure("Seuls les owners peuvent utiliser cette commande.")

    return commands.check(predicate)


def is_app_owner(user: discord.abc.User) -> bool:
    return user.id in app_owner_ids


def require_app_owner():
    async def predicate(ctx: commands.Context) -> bool:
        if not is_app_owner(ctx.author):
            raise commands.CheckFailure("Seul le createur du bot peut utiliser cette commande.")

        return True

    return commands.check(predicate)


def find_role(guild: discord.Guild, query: str) -> discord.Role | None:
    query = query.strip()

    if query.startswith("<@&") and query.endswith(">"):
        query = query[3:-1]

    if query.isdigit():
        return guild.get_role(int(query))

    query_lower = query.lower()
    return discord.utils.find(lambda role: role.name.lower() == query_lower, guild.roles)


async def resolve_member(ctx: commands.Context, query: str) -> discord.Member:
    query = query.strip()

    if query.startswith("<@") and query.endswith(">"):
        query = query.replace("<@", "").replace("!", "").replace(">", "")

    if query.isdigit():
        member = ctx.guild.get_member(int(query))
        if member:
            return member
        return await ctx.guild.fetch_member(int(query))

    converter = commands.MemberConverter()
    return await converter.convert(ctx, query)


def role_has_dangerous_role_permission(guild_id: int, role_id: int) -> bool:
    return role_has_permission(guild_id, role_id, "addrole") or role_has_permission(guild_id, role_id, "delrole")


def can_manage_role(ctx: commands.Context, role: discord.Role) -> tuple[bool, str]:
    bot_member = ctx.guild.me

    if role >= bot_member.top_role:
        return False, "Je ne peux pas gerer ce role car il est au-dessus ou egal a mon role."

    if isinstance(ctx.author, discord.Member) and not is_bot_owner(ctx.author):
        if role >= ctx.author.top_role:
            return False, "Tu ne peux pas gerer un role au-dessus ou egal a ton role."

    if role_has_dangerous_role_permission(ctx.guild.id, role.id):
        return False, "Tu ne peux pas gerer un role qui possede la permission addrole ou delrole."

    return True, ""


@bot.event
async def on_ready() -> None:
    global app_owner_ids
    application = await bot.application_info()
    app_owner_ids = {application.owner.id}
    await apply_saved_presence()
    print(f"Connecte en tant que {bot.user} ({bot.user.id})")


HELP_SECTIONS = {
    "moderation": {
        "label": "Moderation",
        "description": "Ban, unban, kick et clear",
        "title": "Commandes moderation",
        "commands": [
            "`.ban <@user|id> [raison]`\nPermet de bannir un membre",
            "`.unban <id> [raison]`\nPermet de debannir un utilisateur",
            "`.kick <@user|id> [raison]`\nPermet de kick un utilisateur du serveur",
            "`.clear <nombre>`\nPermet de supprimer un certain nombre de messages",
            "`.derank <@user|id>`\nPermet de retirer tous les roles d'un membre",
        ],
    },
    "roles": {
        "label": "Roles",
        "description": "Ajouter ou retirer des roles",
        "title": "Commandes roles",
        "commands": [
            "`.addrole <@user|id> <@role|id|nom>`\nPermet d'ajouter un role a un utilisateur",
            "`.delrole <@user|id> <@role|id|nom>`\nPermet de retirer un role a un utilisateur",
        ],
    },
    "permissions": {
        "label": "Permissions",
        "description": "Setperm, unsetperm et perm",
        "title": "Commandes permissions",
        "commands": [
            "`.setperm <@role|id|nom> <permission>`\nPermet de donner une permission bot a un role",
            "`.unsetperm <@role|id|nom> <permission>`\nPermet de retirer une permission bot a un role",
            "`.perm`\nPermet de voir les permissions disponibles",
            "`.help`\nPermet de voir le menu d'aide",
        ],
    },
    "bot": {
        "label": "Bot",
        "description": "Nom, image et couleur",
        "title": "Commandes bot",
        "commands": [
            "`.botname <nouveau nom>`\nPermet de changer le nom du bot",
            "`.botpic <url>`\nPermet de changer la photo de profil du bot",
            "`.colorbot <couleur>`\nPermet de changer la couleur de la barre des embeds",
            "`.botlive <texte>`\nPermet de mettre le bot en direct",
            "`.botliveoff`\nPermet de retirer le direct du bot",
            "`.owner <@user|id>`\nPermet d'ajouter un owner au bot",
            "`.unowner <@user|id>`\nPermet de retirer un owner du bot",
            "`.autologs`\nPermet de creer les salons de logs",
            "Couleurs disponibles\nrose, noir, bleu, rouge, vert, jaune, violet, orange, #ff4fa3",
        ],
    },
}


def help_embed(section_key: str, guild: discord.Guild | None) -> discord.Embed:
    section = HELP_SECTIONS[section_key]
    embed = discord.Embed(
        title=section["title"],
        description="\n\n".join(section["commands"]),
        color=get_embed_color(guild),
    )
    return embed


def help_home_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="Help",
        description="Selectionne une categorie dans le menu.\nPrefix actuel: `.`",
        color=get_embed_color(guild),
    )
    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=section["label"],
                description=section["description"],
                value=section_key,
            )
            for section_key, section in HELP_SECTIONS.items()
        ]
        super().__init__(
            placeholder="Selectionne une categorie",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="helpbot_selector",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=help_embed(self.values[0], interaction.guild), view=self.view)


class HelpView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(HelpSelect())


PERM_SECTIONS = {
    "roles": {
        "label": "Role",
        "description": "Permissions pour gerer les roles",
        "title": "Permissions role",
        "content": (
            "`.addrole`\n"
            "Permet d'utiliser .addrole\n\n"
            "`.delrole`\n"
            "Permet d'utiliser .delrole\n\n"
            "`.setperm`\n"
            "Permet d'utiliser .setperm\n\n"
            "`.unsetperm`\n"
            "Permet d'utiliser .unsetperm\n\n"
            "`.help`\n"
            "Permet d'utiliser .help\n\n"
            "`.derank`\n"
            "Permet d'utiliser .derank"
        ),
    },
    "moderation": {
        "label": "Moderation",
        "description": "Permissions de moderation",
        "title": "Permissions moderation",
        "content": (
            "`.ban`\n"
            "Permet d'utiliser .ban\n\n"
            "`.kick`\n"
            "Permet d'utiliser .kick\n\n"
            "`.unban`\n"
            "Permet d'utiliser .unban\n\n"
            "`.clear`\n"
            "Permet d'utiliser .clear"
        ),
    },
}


def perm_home_embed(guild: discord.Guild | None) -> discord.Embed:
    return discord.Embed(
        title="Permissions disponibles",
        description=(
            "Selectionne une categorie dans le menu.\n\n"
            "`.setperm @role permission`\n"
            "Permet de donner une permission a un role\n\n"
            "`.unsetperm @role permission`\n"
            "Permet de retirer une permission a un role"
        ),
        color=get_embed_color(guild),
    )


def perm_section_embed(section_key: str, guild: discord.Guild | None) -> discord.Embed:
    section = PERM_SECTIONS[section_key]
    return discord.Embed(
        title=section["title"],
        description=section["content"],
        color=get_embed_color(guild),
    )


class PermSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=section["label"],
                description=section["description"],
                value=section_key,
            )
            for section_key, section in PERM_SECTIONS.items()
        ]
        super().__init__(
            placeholder="Selectionne une categorie",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="perm_selector",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=perm_section_embed(self.values[0], interaction.guild),
            view=self.view,
        )


class PermView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(PermSelect())


@bot.command(name="help")
@require_bot_permission("help")
async def help_command(ctx: commands.Context) -> None:
    await ctx.send(embed=help_home_embed(ctx.guild), view=HelpView())


@bot.command(name="perm")
async def perm(ctx: commands.Context) -> None:
    await ctx.send(embed=perm_home_embed(ctx.guild), view=PermView())


def split_role_and_permission(args: str) -> tuple[str | None, str | None]:
    parts = args.rsplit(" ", 1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip(), parts[1].strip().lower()


@bot.command(name="setperm")
@require_admin_or_bot_permission("setperm")
async def setperm(ctx: commands.Context, *, args: str) -> None:
    role_query, permission = split_role_and_permission(args)
    if not role_query or not permission:
        await ctx.send("Utilisation: `.setperm <@role|id|nom> <permission>`")
        return

    permission = permission.lower()
    if permission not in MANAGED_PERMISSIONS:
        await ctx.send(f"Permission inconnue. Permissions: `{', '.join(sorted(MANAGED_PERMISSIONS))}`")
        return

    role = find_role(ctx.guild, role_query)
    if not role:
        await ctx.send("Role introuvable.")
        return

    guild_permissions = get_guild_permissions(ctx.guild.id)
    role_permissions = guild_permissions.setdefault(role_key(role.id), [])

    if permission not in role_permissions:
        role_permissions.append(permission)
        role_permissions.sort()
        save_permissions(permissions_data)

    await send_action_log(
        ctx.guild,
        "setperm",
        "Permission ajoutee",
        [
            f"Commande: .setperm",
            f"Utilisateur: {ctx.author.mention}",
            f"Role: {role.mention}",
            f"Permission: {permission}",
        ],
    )
    await ctx.send(f"Permission `{permission}` ajoutee au role `{role.name}`.")


@bot.command(name="unsetperm")
@require_admin_or_bot_permission("unsetperm")
async def unsetperm(ctx: commands.Context, *, args: str) -> None:
    role_query, permission = split_role_and_permission(args)
    if not role_query or not permission:
        await ctx.send("Utilisation: `.unsetperm <@role|id|nom> <permission>`")
        return

    permission = permission.lower()
    if permission not in MANAGED_PERMISSIONS:
        await ctx.send(f"Permission inconnue. Permissions: `{', '.join(sorted(MANAGED_PERMISSIONS))}`")
        return

    role = find_role(ctx.guild, role_query)
    if not role:
        await ctx.send("Role introuvable.")
        return

    guild_permissions = get_guild_permissions(ctx.guild.id)
    role_permissions = guild_permissions.get(role_key(role.id), [])

    if permission in role_permissions:
        role_permissions.remove(permission)
        if role_permissions:
            guild_permissions[role_key(role.id)] = role_permissions
        else:
            guild_permissions.pop(role_key(role.id), None)
        save_permissions(permissions_data)

    await send_action_log(
        ctx.guild,
        "setperm",
        "Permission retiree",
        [
            f"Commande: .unsetperm",
            f"Utilisateur: {ctx.author.mention}",
            f"Role: {role.mention}",
            f"Permission: {permission}",
        ],
    )
    await ctx.send(f"Permission `{permission}` retiree du role `{role.name}`.")


@bot.command(name="addrole")
@require_bot_permission("addrole")
async def addrole(ctx: commands.Context, user_query: str, *, role_query: str) -> None:
    member = await resolve_member(ctx, user_query)
    role = find_role(ctx.guild, role_query)

    if not role:
        await ctx.send("Role introuvable.")
        return

    allowed, reason = can_manage_role(ctx, role)
    if not allowed:
        await ctx.send(reason)
        return

    await member.add_roles(role, reason=f"Commande addrole par {ctx.author}")
    refreshed_member = await ctx.guild.fetch_member(member.id)
    if role.id not in [member_role.id for member_role in refreshed_member.roles]:
        await ctx.send(
            "Discord n'a pas garde le role sur ce membre. "
            "Verifie que le role du bot est au-dessus du role vise et que le bot a Gerer les roles."
        )
        return

    await send_action_log(
        ctx.guild,
        "addrole",
        "Role ajoute",
        [
            f"Commande: .addrole",
            f"Utilisateur: {ctx.author.mention}",
            f"Membre: {member.mention}",
            f"Role: {role.mention}",
        ],
    )
    await ctx.send(f"Role `{role.name}` ajoute a {member.mention}.")


@bot.command(name="delrole")
@require_bot_permission("delrole")
async def delrole(ctx: commands.Context, user_query: str, *, role_query: str) -> None:
    member = await resolve_member(ctx, user_query)
    role = find_role(ctx.guild, role_query)

    if not role:
        await ctx.send("Role introuvable.")
        return

    allowed, reason = can_manage_role(ctx, role)
    if not allowed:
        await ctx.send(reason)
        return

    await member.remove_roles(role, reason=f"Commande delrole par {ctx.author}")
    refreshed_member = await ctx.guild.fetch_member(member.id)
    if role.id in [member_role.id for member_role in refreshed_member.roles]:
        await ctx.send(
            "Discord n'a pas retire le role de ce membre. "
            "Verifie que le role du bot est au-dessus du role vise et que le bot a Gerer les roles."
        )
        return

    await send_action_log(
        ctx.guild,
        "delrole",
        "Role retire",
        [
            f"Commande: .delrole",
            f"Utilisateur: {ctx.author.mention}",
            f"Membre: {member.mention}",
            f"Role: {role.mention}",
        ],
    )
    await ctx.send(f"Role `{role.name}` retire de {member.mention}.")


@bot.command(name="derank")
@require_bot_permission("derank")
async def derank(ctx: commands.Context, user_query: str) -> None:
    member = await resolve_member(ctx, user_query)

    if member == ctx.author and not is_bot_owner(ctx.author):
        await ctx.send("Tu ne peux pas te derank toi-meme.")
        return

    removable_roles = []
    blocked_roles = []

    for role in member.roles:
        if role == ctx.guild.default_role:
            continue

        allowed, reason = can_manage_role(ctx, role)
        if allowed:
            removable_roles.append(role)
        else:
            blocked_roles.append(f"{role.name}: {reason}")

    if not removable_roles:
        await ctx.send("Aucun role retirable sur ce membre.")
        return

    await member.remove_roles(*removable_roles, reason=f"Commande derank par {ctx.author}")
    refreshed_member = await ctx.guild.fetch_member(member.id)
    remaining_removed_roles = [
        role.name for role in removable_roles if role.id in [member_role.id for member_role in refreshed_member.roles]
    ]

    if remaining_removed_roles:
        await ctx.send(
            "Discord n'a pas retire certains roles: "
            + ", ".join(remaining_removed_roles)
            + ". Verifie la hierarchie du role du bot."
        )
        return

    await send_action_log(
        ctx.guild,
        "derank",
        "Derank",
        [
            f"Commande: .derank",
            f"Utilisateur: {ctx.author.mention}",
            f"Membre: {member.mention}",
            "Roles retires: " + ", ".join(role.name for role in removable_roles),
        ],
    )

    message = f"{member.mention} a été derank."
    if blocked_roles:
        message += "\nCertains roles n'ont pas ete retires car ils sont proteges ou trop hauts."

    await ctx.send(message)


@bot.command(name="ban")
@require_bot_permission("ban")
async def ban(ctx: commands.Context, user_query: str, *, reason: str = "Aucune raison") -> None:
    member = await resolve_member(ctx, user_query)

    if member == ctx.author:
        await ctx.send("Tu ne peux pas te bannir toi-meme.")
        return

    await member.ban(reason=f"{reason} - par {ctx.author}")
    await ctx.send(f"`{member}` a ete banni. Raison: {reason}")


@bot.command(name="unban")
@require_bot_permission("unban")
async def unban(ctx: commands.Context, user_id: int, *, reason: str = "Aucune raison") -> None:
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=f"{reason} - par {ctx.author}")
    await ctx.send(f"`{user}` a ete debanni. Raison: {reason}")


@bot.command(name="kick")
@require_bot_permission("kick")
async def kick(ctx: commands.Context, user_query: str, *, reason: str = "Aucune raison") -> None:
    member = await resolve_member(ctx, user_query)

    if member == ctx.author:
        await ctx.send("Tu ne peux pas te kick toi-meme.")
        return

    await member.kick(reason=f"{reason} - par {ctx.author}")
    await ctx.send(f"`{member}` a ete kick. Raison: {reason}")


@bot.command(name="clear")
@require_bot_permission("clear")
async def clear(ctx: commands.Context, amount: int) -> None:
    if amount < 1 or amount > 100:
        await ctx.send("Le nombre doit etre entre 1 et 100.")
        return

    deleted = await ctx.channel.purge(limit=amount + 1)
    message = await ctx.send(f"{len(deleted) - 1} message(s) supprime(s).")
    await message.delete(delay=4)


@bot.command(name="botname")
@require_admin_or_owner()
async def botname(ctx: commands.Context, *, new_name: str) -> None:
    new_name = new_name.strip()
    if len(new_name) < 2 or len(new_name) > 32:
        await ctx.send("Le nom du bot doit faire entre 2 et 32 caracteres.")
        return

    await bot.user.edit(username=new_name)
    await ctx.send(f"Nom du bot change en `{new_name}`.")


@bot.command(name="botpic")
@require_admin_or_owner()
async def botpic(ctx: commands.Context, image_url: str) -> None:
    if not image_url.startswith(("http://", "https://")):
        await ctx.send("Envoie une URL valide qui commence par `http://` ou `https://`.")
        return

    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                await ctx.send("Impossible de telecharger l'image.")
                return

            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                await ctx.send("L'URL doit pointer vers une image.")
                return

            image_bytes = await response.read()

    if len(image_bytes) > 8 * 1024 * 1024:
        await ctx.send("L'image est trop lourde. Prends une image de moins de 8 Mo.")
        return

    await bot.user.edit(avatar=image_bytes)
    await ctx.send("Photo de profil du bot changee.")


@bot.command(name="colorbot")
@require_admin_or_owner()
async def colorbot(ctx: commands.Context, *, color_value: str) -> None:
    color = parse_color(color_value)
    if color is None:
        await ctx.send(
            "Couleur invalide. Exemples: `rose`, `noir`, `bleu`, `rouge`, `vert`, `#ff4fa3`."
        )
        return

    guild_settings = get_guild_settings(ctx.guild.id)
    guild_settings["embed_color"] = color
    save_settings(settings_data)

    embed = discord.Embed(
        title="Couleur du bot mise a jour",
        description=f"La barre des embeds est maintenant `{color_value}`.",
        color=discord.Color(color),
    )
    await ctx.send(embed=embed)


@bot.command(name="botlive")
@require_admin_or_owner()
async def botlive(ctx: commands.Context, *, text: str) -> None:
    text = text.strip()
    if len(text) < 2:
        await ctx.send("Mets un texte pour le live. Exemple: `.botlive la tendance de cette ete ?`")
        return

    url = "https://www.twitch.tv/discord"
    global_settings = get_global_settings()
    global_settings["activity"] = {
        "type": "streaming",
        "name": text,
        "url": url,
    }
    save_settings(settings_data)

    await bot.change_presence(activity=discord.Streaming(name=text, url=url))
    await ctx.send(f"Live du bot active: `{text}`")


@bot.command(name="botliveoff")
@require_admin_or_owner()
async def botliveoff(ctx: commands.Context) -> None:
    global_settings = get_global_settings()
    global_settings.pop("activity", None)
    save_settings(settings_data)

    await bot.change_presence(activity=None)
    await ctx.send("Live du bot retire.")


@bot.command(name="autologs")
@require_admin_or_owner()
async def autologs(ctx: commands.Context) -> None:
    created_channels = {
        "setperm": await find_or_create_text_channel(ctx.guild, "logs-setperm"),
        "addrole": await find_or_create_text_channel(ctx.guild, "logs-addrole"),
        "delrole": await find_or_create_text_channel(ctx.guild, "logs-delrole"),
        "derank": await find_or_create_text_channel(ctx.guild, "logs-derank"),
    }

    guild_settings = get_guild_settings(ctx.guild.id)
    guild_settings["logs"] = {
        log_name: channel.id for log_name, channel in created_channels.items()
    }
    save_settings(settings_data)

    embed = discord.Embed(
        title="Autologs active",
        description=(
            "Les salons de logs sont configures.\n\n"
            "#logs-setperm\n"
            "Logs des commandes .setperm et .unsetperm\n\n"
            "#logs-addrole\n"
            "Logs des commandes .addrole\n\n"
            "#logs-delrole\n"
            "Logs des commandes .delrole\n\n"
            "#logs-derank\n"
            "Logs des commandes .derank"
        ),
        color=get_embed_color(ctx.guild),
    )
    await ctx.send(embed=embed)


@bot.command(name="owner")
@require_app_owner()
async def owner(ctx: commands.Context, user_query: str) -> None:
    member = await resolve_member(ctx, user_query)
    guild_owners = get_guild_owners(ctx.guild.id)
    member_id = str(member.id)

    if member_id not in guild_owners:
        guild_owners.append(member_id)
        save_owners(owners_data)

    await ctx.send(f"`{member}` est maintenant owner du bot.")


@bot.command(name="unowner")
@require_app_owner()
async def unowner(ctx: commands.Context, user_query: str) -> None:
    member = await resolve_member(ctx, user_query)
    guild_owners = get_guild_owners(ctx.guild.id)
    member_id = str(member.id)

    if member_id in guild_owners:
        guild_owners.remove(member_id)
        save_owners(owners_data)

    await ctx.send(f"`{member}` n'est plus owner du bot.")


@setperm.error
@unsetperm.error
@botname.error
@botpic.error
@colorbot.error
@botlive.error
@botliveoff.error
@owner.error
@unowner.error
async def admin_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Tu n'as pas la permission d'utiliser cette commande.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(str(error))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argument manquant. Fais `.help` pour voir les commandes.")
    elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.HTTPException):
        original = str(error.original)
        if "Too many users have this username" in original:
            await ctx.send("Ce nom est deja trop utilise sur Discord. Essaie un autre nom pour le bot.")
        elif "username" in original.lower():
            await ctx.send("Discord a refuse ce nom. Essaie un nom different.")
        else:
            await ctx.send(f"Erreur Discord: {error.original}")
    else:
        await ctx.send(f"Erreur: {error}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if hasattr(ctx.command, "on_error"):
        return

    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send(str(error))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argument manquant. Fais `.help` pour voir les commandes.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Argument invalide. Verifie l'utilisateur, le role ou l'ID.")
    elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.Forbidden):
        await ctx.send(
            "Je n'ai pas la permission Discord necessaire. "
            "Verifie que mon role est au-dessus du role vise et que j'ai la permission Gerer les roles."
        )
    elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.HTTPException):
        await ctx.send(f"Discord a refuse l'action: {error.original}")
    elif isinstance(error, discord.Forbidden):
        await ctx.send("Je n'ai pas les permissions Discord necessaires.")
    else:
        await ctx.send(f"Erreur: {error}")


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN est manquant. Mets ton token dans le fichier .env")

bot.run(token)
