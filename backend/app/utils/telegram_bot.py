import asyncio
import httpx
from typing import Optional
from sqlalchemy import select, func, case

from app.core.config import settings
from app.core.database import async_session
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.ingest_pipeline.orchestrator import run_full_pipeline


def _build_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length + " (0%)"
    pct = min(max(current / total, 0.0), 1.0)
    filled = int(round(length * pct))
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} ({int(pct * 100)}%)"


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
            await send_reply(chat_id, f"⚠️ Website ID `{website_id}` not found.")
            return

        # 1. Page status breakdown
        page_stats = await session.execute(
            select(
                func.count(ScrapedPage.id).label("total"),
                func.count(case((ScrapedPage.status == PageProcessStatus.COMPLETED, 1))).label("completed"),
                func.count(case((ScrapedPage.status == PageProcessStatus.IN_PROGRESS, 1))).label("in_progress"),
                func.count(case((ScrapedPage.status == PageProcessStatus.PENDING, 1))).label("pending"),
                func.count(case((ScrapedPage.status == PageProcessStatus.FAILED, 1))).label("failed"),
            ).where(ScrapedPage.web_id == website_id)
        )
        p = page_stats.one()
        total_pages = p.total or 0
        pages_done = p.completed or 0
        pages_crawling = p.in_progress or 0
        pages_pending = p.pending or 0
        pages_failed = p.failed or 0

        # 2. Chunk stats
        chunk_stats = await session.execute(
            select(
                func.count(Chunk.id).label("total_chunks"),
                func.coalesce(func.sum(Chunk.token_count), 0).label("total_tokens"),
                func.count(case((Chunk.has_qgen.is_(True), 1))).label("qgen_processed_chunks"),
            )
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == website_id)
        )
        c = chunk_stats.one()
        total_chunks = c.total_chunks or 0
        total_tokens = c.total_tokens or 0
        chunks_qgen_done = c.qgen_processed_chunks or 0

        # 3. Question & Qdrant sync stats
        q_stats = await session.execute(
            select(
                func.count(GeneratedQuestion.id).label("total_q"),
                func.count(case((GeneratedQuestion.is_synced_qdrant.is_(True), 1))).label("synced_q"),
            )
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == website_id)
        )
        q = q_stats.one()
        total_questions = q.total_q or 0
        synced_qdrant = q.synced_q or 0

        # Status badge formatting
        status_icons = {
            WebsiteScrapeStatus.PENDING: "⏳ PENDING",
            WebsiteScrapeStatus.IN_PROGRESS: "🔄 IN PROGRESS",
            WebsiteScrapeStatus.COMPLETED: "✅ COMPLETED",
            WebsiteScrapeStatus.FAILED: "❌ FAILED",
        }
        status_label = status_icons.get(website.status, str(website.status))

        # Visual progress bars
        page_bar = _build_progress_bar(pages_done, total_pages)
        qgen_bar = _build_progress_bar(chunks_qgen_done, total_chunks)
        sync_bar = _build_progress_bar(synced_qdrant, total_questions)

        msg = (
            f"📊 *Ingestion Status — Site #{website_id}*\n"
            f"🌐 `{website.url}`\n"
            f"• *Status:* {status_label}\n"
        )
        if website.error_message:
            msg += f"• *Error:* `{website.error_message[:200]}`\n"

        msg += (
            f"\n📄 *Stage 1: Web Crawling*\n"
            f"{page_bar}\n"
            f"• Total Discovered: `{total_pages}`\n"
            f"• Scraped: `{pages_done}` | Crawling: `{pages_crawling}`\n"
            f"• Pending: `{pages_pending}` | Failed: `{pages_failed}`\n"
            f"\n🧩 *Stage 2: Chunking & Tokenization*\n"
            f"• Substantive Chunks: `{total_chunks}`\n"
            f"• Est. Tokens: `{total_tokens:,}`\n"
            f"\n🤖 *Stage 3: Question Generation (QGen)*\n"
            f"{qgen_bar}\n"
            f"• Chunks Processed: `{chunks_qgen_done}/{total_chunks}`\n"
            f"• Synthetic Qs Created: `{total_questions}`\n"
            f"\n⚡ *Stage 4: Vector Indexing (Qdrant)*\n"
            f"{sync_bar}\n"
            f"• Points Synced: `{synced_qdrant}/{total_questions}`\n"
        )

        await send_reply(chat_id, msg)


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