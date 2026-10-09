import asyncio
import inspect
import httpx
from typing import Optional
from urllib.parse import urlparse
from sqlalchemy import select, func, case, update, text

from app.core.config import settings
from app.core.database import async_session, engine
from app.models.org import Org
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.embeddings.factory import get_embedder
from app.services.ingest_pipeline.orchestrator import run_full_pipeline, get_active_sync_column
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.vector_db.factory import get_vector_db

def _is_truthy(val) -> bool:
    """Safely evaluates booleans, strings ('true'/'false'), or integers."""
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)

use_prod_coll = _is_truthy(getattr(settings, "collection_name_use_prod", False))

TELEGRAM_BOT_TOKEN = (
    settings.telegram_bot_token
    if settings.telegram_bot_use_prod
    else settings.telegram_bot_token_not_prod
)


def _mask_secret(key: Optional[str]) -> str:
    if not key:
        return "<NOT SET>"
    if len(key) <= 8:
        return "********"
    return f"{key[:4]}...{key[-4:]}"


def _is_truthy(val) -> bool:
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def _safe_db_summary(raw_url: Optional[str]) -> str:
    if not raw_url:
        return "<NOT SET>"
    try:
        parsed = urlparse(raw_url)
        db_name = parsed.path.lstrip("/") or "<no db>"
        host_port = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
        return f"db='{db_name}' @ host='{host_port}'"
    except Exception:
        return "<unparseable url>"


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


async def handle_check_environment_command(chat_id: int | str):
    """Audits active environment variables and validates live connections asynchronously."""
    await send_reply(chat_id, "🔍 *Auditing active environment and live connections...*")

    # 1. Environment Configurations
    use_prod_collection = _is_truthy(getattr(settings, "collection_name_use_prod", False))
    use_prod_cache = _is_truthy(getattr(settings, "semantic_cache_index_name_use_prod", False))
    use_prod_db = _is_truthy(getattr(settings, "database_url_use_prod", False))

    active_collection = settings.resolved_collection_name

    active_semantic_cache = (
        getattr(settings, "semantic_cache_index_name", "<NOT SET>")
        if use_prod_cache
        else getattr(settings, "semantic_cache_index_name_not_prod", getattr(settings, "semantic_cache_index_name", "<NOT SET>"))
    )

    db_url = getattr(settings, "DATABASE_URL", None) or getattr(settings, "database_url", None)
    target_dim = getattr(settings, "embedding_dimension", None) or getattr(settings, "vector_dim", None)

    msg_lines = [
        "⚙️ *ACTIVE ENVIRONMENT AUDIT*",
        "---",
        f"• *Embedder Provider:* `{getattr(settings, 'embedding_provider', '<NOT SET>')}`",
        f"• *Embedder Model:* `{getattr(settings, 'embedding_model', '<NOT SET>')}`",
        f"• *Embedder API Key:* `{_mask_secret(getattr(settings, 'embedding_api_key', None))}`",
        f"• *Target Vector Dim:* `{target_dim}`",
        f"• *Active Collection:* `{active_collection}` (Prod: `{use_prod_collection}`)",
        f"• *Active Semantic Cache:* `{active_semantic_cache}` (Prod: `{use_prod_cache}`)",
        f"• *Database Host/Name:* `{_safe_db_summary(db_url)}` (Prod: `{use_prod_db}`)",
        "",
        "🔌 *LIVE SERVICE CONNECTIONS*",
        "---",
    ]

    # 2. Database Connection Check
    try:
        async with engine.connect() as conn:
            live_db = await conn.scalar(text("SELECT current_database()"))
            live_user = await conn.scalar(text("SELECT current_user"))
            db_host = f"{engine.url.host}:{engine.url.port or 'default'}"
            msg_lines.append(f"✅ *Database:* Connected (`{live_db}` as `{live_user}` @ `{db_host}`)")
    except Exception as e:
        msg_lines.append(f"❌ *Database:* Failed (`{str(e)[:100]}`)")

    # 3. Embedder Verification Check
    try:
        embedder = get_embedder()
        res = await embedder.embed(["MSEUF BSCS curriculum"])
        vector_size = len(res[0].values)

        if target_dim:
            if vector_size == target_dim:
                msg_lines.append(f"✅ *Embedder:* `{type(embedder).__name__}` generated `{vector_size}d` vector (Matched target)")
            else:
                msg_lines.append(f"⚠️ *Embedder:* Dimension mismatch! Expected `{target_dim}d`, got `{vector_size}d`")
        else:
            msg_lines.append(f"✅ *Embedder:* `{type(embedder).__name__}` generated `{vector_size}d` vector")
    except Exception as e:
        msg_lines.append(f"❌ *Embedder:* Failed (`{str(e)[:100]}`)")

    # 4. Vector Database Verification Check
    try:
        vdb = get_vector_db()
        client = getattr(vdb, "client", getattr(vdb, "async_client", None))

        if client is not None and hasattr(client, "get_collection"):
            get_coll_method = getattr(client, "get_collection")
            if inspect.iscoroutinefunction(get_coll_method):
                coll_info = await get_coll_method(collection_name=active_collection)
            else:
                coll_info = get_coll_method(collection_name=active_collection)

            status = getattr(coll_info, "status", "UNKNOWN")
            points_count = getattr(coll_info, "points_count", getattr(coll_info, "vectors_count", "N/A"))
            msg_lines.append(
                f"✅ *Vector DB:* Connected to `{active_collection}`\n"
                f"   • Status: `{status}` | Points Count: `{points_count}`"
            )
        else:
            msg_lines.append(f"⚠️ *Vector DB:* Initialized `{type(vdb).__name__}`, but client handle is inaccessible.")
    except Exception as e:
        msg_lines.append(f"❌ *Vector DB:* Failed (`{str(e)[:100]}`)")

    await send_reply(chat_id, "\n".join(msg_lines))


async def handle_clear_cache_command(chat_id: int | str, org_id: Optional[int] = None):
    """
    Clears semantic cache entries.
    If org_id is provided, bumps content_version in Postgres to immediately invalidate
    tenant-specific cache lookups. If org_id is omitted or 'all', flushes the entire cache index.
    """
    try:
        if org_id is not None:
            async with async_session() as session:
                org = await session.get(Org, org_id)
                if not org:
                    await send_reply(chat_id, f"⚠️ Organization `#{org_id}` not found.")
                    return

                await session.execute(
                    update(Org)
                    .where(Org.id == org_id)
                    .values(content_version=Org.content_version + 1)
                )
                await session.commit()
                await session.refresh(org)

            await send_reply(
                chat_id,
                f"🧹 *Tenant Cache Invalidated!*\n"
                f"• *Org ID:* `{org_id}` ({org.name})\n"
                f"• *New Content Version:* `v{org.content_version}`\n"
                f"All prior semantic cache entries for this organization are now unreachable.",
            )
        else:
            cache = get_semantic_cache()
            await cache.clear()
            await send_reply(chat_id, "🧹 *Semantic Cache Flushed!*\nAll cached query entries have been cleared.")
    except Exception as e:
        print(f"[Telegram Clear Cache Error]: {e}")
        await send_reply(chat_id, f"❌ Failed to clear cache:\n`{str(e)[:300]}`")


async def handle_query_command(chat_id: int | str, org_id: int, query_text: str):
    """Executes the full hybrid retrieval + cross-encoder + QA pipeline for a specific org."""
    if not query_text:
        await send_reply(
            chat_id,
            "⚠️ *Usage:* `/query <org_id> <your question>`\n"
            "Example: `/query 1 What are the admission requirements for BSCS?`",
        )
        return

    await send_reply(
        chat_id, 
        f"🔍 *[Org #{org_id}] Searching knowledge base for:*\n_{query_text[:120]}_..."
    )

    try:
        pipeline = QueryPipeline()
        req = PipelineQueryRequest(query=query_text, org_id=org_id, top_k=5)
        response = await pipeline.execute(req)

        source_icon = "⚡" if response.is_cached else "🤖"
        msg = f"{source_icon} Answer:\n\n{response.answer}\n"

        if response.sources:
            msg += "\n🔗 Sources:\n"
            for s in response.sources[:4]:
                msg += f"• {s}\n"

        msg += f"\n---\nOrg: #{org_id} | Source: {response.source.upper()} | Collection: {pipeline.collection_name}"
        
        await send_reply(chat_id, msg, parse_mode=None)

    except Exception as e:
        print(f"[Telegram Query Error]: {e}")
        await send_reply(chat_id, f"❌ Query Failed:\n{str(e)[:300]}", parse_mode=None)


async def run_pipeline_with_notifications(website_id: int, chat_id: Optional[int | str] = None):
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
        await send_reply(
            chat_id,
            f"🚀 *Ingestion Started*\n"
            f"• *Website ID:* `{website_id}`\n"
            f"• *Org ID:* `{org_id}`\n"
            f"• *Target URL:* {target_url}\n"
            f"• *Target Collection:* `{settings.resolved_collection_name}`\n"
            f"• *Dense Model:* `{dense_info}`\n"
            f"• *Sparse Model:* `{sparse_info}`\n"
            f"• *Active Sync Flag:* `{sync_col.key}`",
        )

    try:
        results = await run_full_pipeline(website_id=website_id)
        if chat_id:
            await send_reply(
                chat_id,
                f"✅ *Pipeline Completed Successfully!*\n"
                f"• *Target Collection:* `{settings.resolved_collection_name}`\n"
                f"• *Dense Model:* `{dense_info}`\n"
                f"• *Sparse Model:* `{sparse_info}`\n"
                f"• *URLs Discovered:* `{results['discovered_urls']}`\n"
                f"• *Pages Scraped:* `{results['scraped_pages']}`\n"
                f"• *Chunks Created:* `{results['created_chunks']}`\n"
                f"• *Questions Generated:* `{results['generated_questions']}`\n"
                f"• *Points Synced ({sync_col.key}):* `{results['synced_qdrant_points']}`",
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
            f"• *Target Collection:* `{settings.resolved_collection_name}`\n"
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
                    raw_text = message.get("text", "").strip()

                    if not chat_id or not raw_text:
                        continue

                    cmd_parts = raw_text.split()
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

                    elif command == "/query":
                        if len(cmd_parts) < 3 or not cmd_parts[1].isdigit():
                            await send_reply(
                                chat_id,
                                "⚠️ *Invalid Format!*\n"
                                "Usage: `/query <org_id> <your question>`\n"
                                "Example: `/query 1 What are the admission requirements for BSCS?`",
                            )
                            continue

                        org_id = int(cmd_parts[1])
                        user_query = " ".join(cmd_parts[2:]).strip()
                        asyncio.create_task(handle_query_command(chat_id, org_id, user_query))

                    elif command in ["/check_environment", "/env"]:
                        asyncio.create_task(handle_check_environment_command(chat_id))

                    elif command == "/clear_cache":
                        org_id_target: Optional[int] = None
                        if len(cmd_parts) > 1:
                            target_arg = cmd_parts[1].strip().lower()
                            if target_arg.isdigit():
                                org_id_target = int(target_arg)
                            elif target_arg != "all":
                                await send_reply(
                                    chat_id,
                                    "⚠️ *Invalid Format!*\n"
                                    "Usage:\n"
                                    "• `/clear_cache <org_id>` - Invalidate cache for a specific organization\n"
                                    "• `/clear_cache all` (or `/clear_cache`) - Clear entire semantic cache index",
                                )
                                continue

                        asyncio.create_task(handle_clear_cache_command(chat_id, org_id_target))

                    elif command in ["/help", "/start"]:
                        await send_reply(
                            chat_id,
                            "🤖 *Knowledge Base Assistant Bot*\n\n"
                            "*Commands:*\n"
                            "• `/query <org_id> <question>` - Ask anything about the organization\n"
                            "• `/scrape <website_id>` - Runs discovery, chunking, and vector indexing\n"
                            "• `/status <website_id>` - Check pipeline progress\n"
                            "• `/clear_cache [org_id|all]` - Clear tenant or entire semantic cache\n"
                            "• `/check_environment` - Audit active config & live service connections\n"
                            "• `/help` - Show instructions",
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Telegram Poller Error]: {e}")
                await asyncio.sleep(5)