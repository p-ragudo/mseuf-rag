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
from app.services.ingest_pipeline.orchestrator import run_full_pipeline, get_active_sync_column

TELEGRAM_BOT_TOKEN = settings.resolved_telegram_token
COLLECTION_NAME = settings.resolved_collection_name


def _build_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length + " (0%)"
    pct = min(max(current / total, 0.0), 1.0)
    filled = int(round(length * pct))
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} ({int(pct * 100)}%)"


async def send_reply(chat_id: int | str, text: str, parse_mode: Optional[str] = "Markdown"):
    if not TELEGRAM_BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 400 and parse_mode:
                payload.pop("parse_mode", None)
                await client.post(url, json=payload, timeout=10.0)
        except Exception as e:
            print(f"[Telegram] Failed to send message to {chat_id}: {e}")


def _get_model_telemetry():
    sync_col = get_active_sync_column()
    dim = getattr(settings, "embedding_dimension", None) or getattr(settings, "vector_dim", 768)
    dense_model = f"{settings.embedding_provider} / {settings.embedding_model} ({dim}d)"
    sparse_model = "fastembed / Qdrant/bm25"
    return sync_col, dense_model, sparse_model


async def run_pipeline_with_notifications(
    website_id: int,
    chat_id: Optional[int | str] = None,
    force_refresh: bool = False,
):
    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            if chat_id:
                await send_reply(chat_id, f"❌ Website ID `{website_id}` not found.")
            return
        target_url = website.url
        org_id = website.org_id

    sync_col, dense_info, sparse_info = _get_model_telemetry()

    if chat_id:
        force_tag = " *(FORCED RE-SCRAPE)*" if force_refresh else ""
        await send_reply(
            chat_id,
            f"🚀 *Ingestion Started*{force_tag}\n"
            f"• *Website ID:* `{website_id}`\n"
            f"• *Org ID:* `{org_id}`\n"
            f"• *Target URL:* {target_url}\n"
            f"• *Target Collection:* `{COLLECTION_NAME}`\n"
            f"• *Dense Model:* `{dense_info}`\n"
            f"• *Sparse Model:* `{sparse_info}`\n"
            f"• *Active Sync Flag:* `{sync_col.key}`",
        )

    try:
        results = await run_full_pipeline(website_id=website_id, force_refresh=force_refresh)
        if chat_id:
            await send_reply(
                chat_id,
                f"✅ *Pipeline Completed Successfully!*\n"
                f"• *Target Collection:* `{COLLECTION_NAME}`\n"
                f"• *URLs Discovered:* `{results['discovered_urls']}`\n"
                f"• *Pages Scraped:* `{results['scraped_pages']}`\n"
                f"• *Chunks Created:* `{results['created_chunks']}`\n"
                f"• *Questions Generated:* `{results['generated_questions']}`\n"
                f"• *Points Synced ({sync_col.key}):* `{results['synced_qdrant_points']}`\n"
                f"• *Swept Pages:* `{results['swept_pages']}`\n"
                f"• *Purged Pages:* `{results['purged_pages']}`",
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

        sync_col, dense_info, sparse_info = _get_model_telemetry()

        q_stats = await session.execute(
            select(
                func.count(GeneratedQuestion.id).label("total_q"),
                func.count(case((sync_col.is_(True), 1))).label("synced_q"),
            )
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == website_id)
        )
        q = q_stats.one()
        total_questions = q.total_q or 0
        synced_active = q.synced_q or 0

        status_icons = {
            WebsiteScrapeStatus.PENDING: "⏳ PENDING",
            WebsiteScrapeStatus.IN_PROGRESS: "🔄 IN PROGRESS",
            WebsiteScrapeStatus.COMPLETED: "✅ COMPLETED",
            WebsiteScrapeStatus.FAILED: "❌ FAILED",
        }
        status_label = status_icons.get(website.status, str(website.status))

        page_bar = _build_progress_bar(pages_done, total_pages)
        qgen_bar = _build_progress_bar(chunks_qgen_done, total_chunks)
        sync_bar = _build_progress_bar(synced_active, total_questions)

        msg = (
            f"📊 *Ingestion Status — Site #{website_id}*\n"
            f"🌐 `{website.url}`\n"
            f"• *Status:* {status_label}\n"
            f"• *Target Collection:* `{COLLECTION_NAME}`\n"
            f"• *Dense Embedder:* `{dense_info}`\n"
            f"• *Sparse Embedder:* `{sparse_info}`\n"
            f"• *Tracking Column:* `{sync_col.key}`\n"
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
            f"• Active Model Synced: `{synced_active}/{total_questions}`\n"
        )

        await send_reply(chat_id, msg)


async def start_telegram_bot_listener():
    if not TELEGRAM_BOT_TOKEN:
        print("[Telegram] TELEGRAM_BOT_TOKEN not configured. Skipping listener.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
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
                for update_obj in data.get("result", []):
                    offset = update_obj["update_id"] + 1
                    message = update_obj.get("message", {})
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
                                "Usage: `/scrape <website_id> [force]`\n"
                                "Examples:\n"
                                "• `/scrape 1` (Standard refresh check)\n"
                                "• `/scrape 1 force` (Force re-crawl & re-chunk all pages)",
                            )
                            continue

                        web_id = int(cmd_parts[1])
                        force = len(cmd_parts) >= 3 and cmd_parts[2].lower() in ("force", "true", "yes", "1")
                        asyncio.create_task(
                            run_pipeline_with_notifications(website_id=web_id, chat_id=chat_id, force_refresh=force)
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
                            "🤖 *Knowledge Base Assistant Bot*\n\n"
                            "*Commands:*\n"
                            "• `/scrape <id> [force]` - Run ingestion (add `force` to bypass 12h cooldown)\n"
                            "• `/status <id>` - Check pipeline progress\n"
                            "• `/help` - Show instructions",
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Telegram Poller Error]: {e}")
                await asyncio.sleep(5)