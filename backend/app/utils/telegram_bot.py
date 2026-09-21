import asyncio
import httpx
from typing import Optional
from app.core.config import settings
from app.services.sql_db.postgres_provider import PostgresDatabaseRepository
from backend.app.services.ingest_pipeline.scraper import scrape_site
from app.services.ingest_pipeline.chunk import process_and_chunk_pages


async def send_reply(chat_id: int | str, text: str):
    """Sends a message back to the originating chat (group, channel, or direct message)."""
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


async def run_pipeline_with_notifications(
    tenant_id: str,
    start_url: str,
    max_depth: int = 1,
    chat_id: Optional[int | str] = None,
):
    """
    Executes crawling and chunking for any tenant, notifying the designated chat at each milestone.
    """
    if chat_id:
        await send_reply(
            chat_id,
            f"🚀 *Ingestion Started*\n"
            f"• *Tenant:* `{tenant_id}`\n"
            f"• *URL:* {start_url}\n"
            f"• *Depth:* {max_depth}",
        )

    repo = PostgresDatabaseRepository(dsn=settings.database_url)
    await repo.connect()

    try:
        # Phase 1: Scrape
        scraped_pages = await scrape_site(
            start_url=start_url,
            tenant_id=tenant_id,
            repo=repo,
            max_depth=max_depth,
        )

        if chat_id:
            await send_reply(
                chat_id,
                f"📥 *Scrape Phase Finished*\n"
                f"• *Tenant:* `{tenant_id}`\n"
                f"• *Pages Checkpointed:* `{len(scraped_pages)}`\n"
                f"• Beginning chunk extraction...",
            )

        # Phase 2: Chunk
        chunks = await process_and_chunk_pages(tenant_id=tenant_id, repo=repo)

        if chat_id:
            await send_reply(
                chat_id,
                f"✅ *Pipeline Completed Successfully!*\n"
                f"• *Tenant:* `{tenant_id}`\n"
                f"• *Chunks Stored:* `{len(chunks)}`\n"
                f"• Status: `PENDING_QGEN`",
            )
    except Exception as e:
        print(f"[{tenant_id}] Pipeline execution failed: {e}")
        if chat_id:
            await send_reply(chat_id, f"❌ *Pipeline Failed for `{tenant_id}`:*\n`{str(e)[:300]}`")
    finally:
        await repo.close()


async def handle_status_command(chat_id: int | str, tenant_id: str):
    """Inspects PostgreSQL row counts for a specified tenant."""
    repo = PostgresDatabaseRepository(dsn=settings.database_url)
    await repo.connect()
    try:
        async with repo._pool.acquire() as conn:
            page_count = await conn.fetchval(
                "SELECT count(*) FROM scraped_pages WHERE tenant_id = $1;", tenant_id
            )
            chunk_count = await conn.fetchval(
                "SELECT count(*) FROM document_chunks WHERE tenant_id = $1;", tenant_id
            )
            pending_qgen = await conn.fetchval(
                "SELECT count(*) FROM document_chunks WHERE tenant_id = $1 AND status = 'PENDING_QGEN';",
                tenant_id,
            )

        await send_reply(
            chat_id,
            f"📊 *Tenant Status: `{tenant_id}`*\n"
            f"• *Scraped Pages:* `{page_count}`\n"
            f"• *Total Chunks:* `{chunk_count}`\n"
            f"• *Pending QGen:* `{pending_qgen}`",
        )
    except Exception as e:
        await send_reply(chat_id, f"⚠️ *Error fetching status:* `{e}`")
    finally:
        await repo.close()


async def start_telegram_bot_listener():
    """Polls Telegram updates and processes commands from any chat member."""
    if not settings.telegram_bot_token:
        print("[Telegram] TELEGRAM_BOT_TOKEN not configured. Skipping listener.")
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    offset = None
    print("[Telegram] Poller active. Accepting commands from all joined chats...")

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

                    # Clean bot mentions in group chats (e.g., "/scrape@MyBot" -> "/scrape")
                    cmd_parts = text.split()
                    command = cmd_parts[0].split("@")[0].lower()

                    if command == "/scrape":
                        # Expected: /scrape <tenant> <url> [depth]
                        if len(cmd_parts) < 3:
                            await send_reply(
                                chat_id,
                                "⚠️ *Invalid Format!*\n"
                                "Usage: `/scrape <tenant> <url> [depth]`\n\n"
                                "Example:\n"
                                "`/scrape mseuf https://mseuf.edu.ph 1`",
                            )
                            continue

                        tenant = cmd_parts[1].lower()
                        target_url = cmd_parts[2]
                        depth = int(cmd_parts[3]) if len(cmd_parts) > 3 and cmd_parts[3].isdigit() else 1

                        # Fire and forget pipeline task in background
                        asyncio.create_task(
                            run_pipeline_with_notifications(
                                tenant_id=tenant,
                                start_url=target_url,
                                max_depth=depth,
                                chat_id=chat_id,
                            )
                        )

                    elif command == "/status":
                        # Expected: /status <tenant>
                        if len(cmd_parts) < 2:
                            await send_reply(
                                chat_id,
                                "⚠️ *Usage:* `/status <tenant>`\nExample: `/status mseuf`",
                            )
                            continue

                        tenant = cmd_parts[1].lower()
                        asyncio.create_task(handle_status_command(chat_id, tenant))

                    elif command in ["/help", "/start"]:
                        await send_reply(
                            chat_id,
                            "🤖 *Multi-Tenant Ingestion Bot*\n\n"
                            "*Commands:*\n"
                            "• `/scrape <tenant> <url> [depth]` - Scrapes and chunks target site (default depth: 1)\n"
                            "• `/status <tenant>` - Inspect database chunk counts\n"
                            "• `/help` - Show this menu",
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Telegram Poller Error]: {e}")
                await asyncio.sleep(5)