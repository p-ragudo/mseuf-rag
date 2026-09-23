import asyncio
import httpx
from typing import Optional
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import async_session
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.ingest_pipeline.orchestrator import run_full_pipeline


async def send_reply(chat_id: int | str, text: str):
    if not settings.telegram_bot_token:
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10.0)
        except Exception as e:
            print(f"[Telegram] Failed to send message to {chat_id}: {e}")


async def run_pipeline_with_notifications(website_id: int, chat_id: Optional[int | str] = None):
    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            if chat_id:
                await send_reply(chat_id, f"❌ Website ID `{website_id}` not found.")
            return
        target_url = website.url
        org_id = website.org_id

    if chat_id:
        await send_reply(
            chat_id,
            f"🚀 *Ingestion Started*\n"
            f"• *Website ID:* `{website_id}`\n"
            f"• *Org ID:* `{org_id}`\n"
            f"• *Target URL:* {target_url}",
        )

    try:
        results = await run_full_pipeline(website_id=website_id)
        if chat_id:
            await send_reply(
                chat_id,
                f"✅ *Pipeline Completed Successfully!*\n"
                f"• *URLs Discovered:* `{results['discovered_urls']}`\n"
                f"• *Pages Scraped:* `{results['scraped_pages']}`\n"
                f"• *Chunks Created:* `{results['created_chunks']}`\n"
                f"• *Questions Generated:* `{results['generated_questions']}`\n"
                f"• *Qdrant Points Synced:* `{results['synced_qdrant_points']}`",
            )
    except Exception as e:
        print(f"[Website {website_id}] Pipeline error: {e}")
        if chat_id:
            await send_reply(chat_id, f"❌ *Pipeline Failed:*\n`{str(e)[:300]}`")


async def handle_status_command(chat_id: int | str, website_id: int):
    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            await send_reply(chat_id, f"⚠️ Website `{website_id}` not found.")
            return

        pages_count = await session.scalar(
            select(func.count(ScrapedPage.id)).where(ScrapedPage.web_id == website_id)
        )
        chunks_count = await session.scalar(
            select(func.count(Chunk.id))
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == website_id)
        )
        questions_count = await session.scalar(
            select(func.count(GeneratedQuestion.id))
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == website_id)
        )

        await send_reply(
            chat_id,
            f"📊 *Status for Website `{website_id}` ({website.url})*\n"
            f"• *Status:* `{website.status}`\n"
            f"• *Pages Discovered:* `{pages_count}`\n"
            f"• *Chunks Stored:* `{chunks_count}`\n"
            f"• *Questions Generated:* `{questions_count}`",
        )


async def start_telegram_bot_listener():
    if not settings.telegram_bot_token:
        print("[Telegram] TELEGRAM_BOT_TOKEN not configured. Skipping listener.")
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    offset = None
    print("[Telegram] Poller active. Listening for commands...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                params = {"timeout": 20}
                if offset:
                    params["offset"] = offset

                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "").strip()

                    if not chat_id or not text:
                        continue

                    cmd_parts = text.split()
                    command = cmd_parts[0].split("@")[0].lower()

                    if command == "/scrape":
                        if len(cmd_parts) < 2 or not cmd_parts[1].isdigit():
                            await send_reply(
                                chat_id,
                                "⚠️ *Invalid Format!*\n"
                                "Usage: `/scrape <website_id>`\n"
                                "Example: `/scrape 1`",
                            )
                            continue

                        web_id = int(cmd_parts[1])
                        asyncio.create_task(
                            run_pipeline_with_notifications(website_id=web_id, chat_id=chat_id)
                        )

                    elif command == "/status":
                        if len(cmd_parts) < 2 or not cmd_parts[1].isdigit():
                            await send_reply(
                                chat_id,
                                "⚠️ *Usage:* `/status <website_id>`\nExample: `/status 1`",
                            )
                            continue

                        web_id = int(cmd_parts[1])
                        asyncio.create_task(handle_status_command(chat_id, web_id))

                    elif command in ["/help", "/start"]:
                        await send_reply(
                            chat_id,
                            "🤖 *Knowledge Base Ingestion Bot*\n\n"
                            "*Commands:*\n"
                            "• `/scrape <website_id>` - Runs discovery, scraping, chunking, and Qdrant sync\n"
                            "• `/status <website_id>` - Check checkpoint progress in PostgreSQL\n"
                            "• `/help` - Show instructions",
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Telegram Poller Error]: {e}")
                await asyncio.sleep(5)