# mypy: ignore-errors
from __future__ import annotations

import discord
from discord import app_commands
from sqlalchemy import select

from app.core.i18n import i18n
from app.db.models import UserPlatformAccount
from app.db.session import SessionLocal
from app.discord_bot.adapter import listing_embed_payload
from app.discord_bot.service import get_or_create_discord_user
from app.favourites.service import favorites
from app.reports.service import ReportValidationError, create_report


class CrousDiscordClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


client = CrousDiscordClient()


@client.tree.command(name="start", description="Start CROUS housing monitoring")
async def start(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with SessionLocal() as session:
        user = await get_or_create_discord_user(
            session,
            interaction.user.id,
            interaction.channel_id or interaction.user.id,
            interaction.user.name,
            interaction.locale.value if interaction.locale else None,
        )
        await session.commit()
    await interaction.followup.send(i18n.text(user.language, "discord-ready"), ephemeral=True)


@client.tree.command(name="favourites", description="Show your saved housing listings")
async def favourites_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with SessionLocal() as session:
        user = await get_or_create_discord_user(
            session,
            interaction.user.id,
            interaction.channel_id or interaction.user.id,
            interaction.user.name,
            interaction.locale.value if interaction.locale else None,
        )
        rows = await favorites(session, user)
        await session.commit()
    if not rows:
        await interaction.followup.send(
            i18n.text(user.language, "housing-no-favorites"), ephemeral=True
        )
        return
    for listing in rows[:10]:
        payload = listing_embed_payload(listing, user.language)
        embed = discord.Embed(
            title=str(payload["title"]),
            description=str(payload["description"]),
            url=str(payload["url"]),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


@client.tree.command(name="report", description="Submit a report")
@app_commands.describe(text="Your report")
async def report_command(interaction: discord.Interaction, text: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with SessionLocal() as session:
        user = await get_or_create_discord_user(
            session,
            interaction.user.id,
            interaction.channel_id or interaction.user.id,
            interaction.user.name,
            interaction.locale.value if interaction.locale else None,
        )
        account = await session.scalar(
            select(UserPlatformAccount).where(
                UserPlatformAccount.platform == "discord",
                UserPlatformAccount.platform_user_id == interaction.user.id,
            )
        )
        try:
            await create_report(session, user, text, account)
        except ReportValidationError:
            await interaction.followup.send(
                i18n.text(user.language, "report-empty"), ephemeral=True
            )
            return
        await session.commit()
    await interaction.followup.send(i18n.text(user.language, "report-sent"), ephemeral=True)


def run() -> None:
    from app.core.config import get_settings

    token = get_settings().discord_bot_token
    if token is None:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    client.run(token.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    run()
