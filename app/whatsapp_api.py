from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

from app.config import (
    validate_config,
    SESSION_DB_PATH,
    DATACRAZY_API_TOKEN,
    DATACRAZY_INSTANCE_ID,
    DATACRAZY_BASE_URL,
)
from app.whatsapp_bridge import (
    DataCrazyBridge,
    parse_datacrazy_api_message,
    IncomingDataCrazyMessage,
)
from app.agent_factory import create_vanessa_agent
from app.log_store import log_store
from app.message_buffer import message_buffer
from app.follow_up_scheduler import follow_up_scheduler_loop, _reset_follow_up

logger = logging.getLogger("vanessa")

app = FastAPI(title="Vanessa — VFO Agent (DataCrazy)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bridge — single source of truth for all agent interactions
bridge = DataCrazyBridge(agent_factory=create_vanessa_agent)

# Admin router
from app.admin_router import router as admin_router
app.include_router(admin_router)
# Admin router alias for instance 2 (same code, different prefix for CF tunnel routing)
from app.admin_router import router as admin_router_2
app.include_router(admin_router_2, prefix="/vfo-2/admin")

# ── DataCrazy polling state ───────────────────────────────────────────────────
_dc_polling_task: asyncio.Task | None = None
_follow_up_task: asyncio.Task | None = None
_dc_processed_message_ids: set[str] = set()
_dc_polling_interval: float = 10.0  # seconds
_dc_rate_limited_until: float = 0.0

# Per-session lock to prevent concurrent processing of the same conversation
_session_locks: dict[str, asyncio.Lock] = {}

def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


@app.on_event("startup")
def startup() -> None:
    validate_config()
    # Ensure SQLite directory exists
    Path(SESSION_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    import app.error_log as error_log
    import app.llm_usage_log as llm_log
    import app.follow_up_state as fus
    error_log.init(SESSION_DB_PATH)
    llm_log.init(SESSION_DB_PATH)
    fus.init_table()
    global _dc_polling_task, _follow_up_task
    logger.info("STARTUP | instance_id=%s db=%s", DATACRAZY_INSTANCE_ID, SESSION_DB_PATH)

    # Start follow-up scheduler
    _follow_up_task = asyncio.create_task(follow_up_scheduler_loop())
    logger.info("🟢 Follow-up scheduler started.")

    # Polling DISABLED — webhook is the sole message source to prevent duplicate messages.
    logger.info("⚠️ DataCrazy polling DISABLED (webhook only) to prevent duplicate messages.")
    # if DATACRAZY_API_TOKEN and DATACRAZY_INSTANCE_ID:
    #     _dc_polling_task = asyncio.create_task(_datacrazy_polling_loop())
    #     logger.info("🟢 Vanessa DataCrazy polling started (interval=%ss).", _dc_polling_interval)
    # else:
    #     logger.warning("Vanessa started WITHOUT DataCrazy polling — check env vars.")


@app.get("/vfo/health")
@app.get("/vfo-2/health")
def health():
    return {"status": "ok"}


# ── DataCrazy webhook (optional — for when DataCrazy pushes) ──────────────────


def _clean_id(value: str) -> str:
    """Strip quotes, curly braces and whitespace from a DataCrazy ID field."""
    return value.strip().strip('"').strip("'").strip('{').strip('}').strip()


from app.media_handler import process_media_url as _process_media_url
from app.media_handler import transcribe_or_extract as _transcribe_or_extract


def _extract_media_url(payload: dict) -> str | None:
    message_data = payload.get("messageData") or {}
    attachments = message_data.get("attachments") or []
    for att in attachments:
        if att.get("url"):
            return att.get("url")

    for key in ("audio", "image", "sticker", "video", "document"):
        media = payload.get(key) or {}
        if media.get("url"):
            return media["url"]

    return None


@app.post("/vfo/webhooks/datacrazy")
@app.post("/vfo-2/webhooks/datacrazy")
async def receive_datacrazy_webhook(request: Request):
    """
    Generic webhook endpoint for DataCrazy.
    Handles multiple payload formats:

    Format A (DataCrazy VFO — JSON object with flat fields):
      {"phone": "558...", "lead_id": "{uuid}", "contactId": "558...",
       "conversation_id": "abc...", "body": "msg"}

    Format B (standard conversation/message objects from polling):
      {"conversation": {...}, "message": {...}}

    Format C (raw text — legacy custom format):
      {externalId,name,phone,conversationId,body}

    Format D (audio messages):
      {"from": "...", "type": "audio", "audio": {"url": "..."}, "messageData": {...}}
    """
    raw_body = await request.body()
    raw_text = raw_body.decode('utf-8').strip()
    logger.debug("Webhook raw body: %s", raw_text[:300])

    # ── Try to parse as JSON first ──────────────────────────────────────────
    try:
        payload = json.loads(raw_body)

        # Handle case where DataCrazy sends payload as a JSON string inside quotes
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                pass

        if isinstance(payload, dict):
            # ── Format D: Media message ───────────────────────────────────────
            if payload.get("type") in {"audio", "image", "sticker"} or any(k in payload for k in ("audio", "image", "sticker")):
                media_url = _extract_media_url(payload)
                if not media_url:
                    logger.warning("Webhook media: no URL found in payload")
                    return {"success": True, "skipped": True, "reason": "no_media_url"}

                phone = _clean_id(str(payload.get("from") or ""))
                conv_id = ""
                lead_id = ""
                name = ""

                message_data = payload.get("messageData") or {}
                contact = message_data.get("contact") or {}
                conv_id = _clean_id(str(message_data.get("conversationId") or ""))
                lead_id = _clean_id(str(contact.get("externalId") or ""))
                phone = _clean_id(str(phone or contact.get("contactId") or ""))
                name = str(contact.get("name") or "").strip()

                if not phone or not conv_id:
                    logger.warning("Webhook media: missing phone=%s conv=%s", phone, conv_id)
                    return {"success": True, "skipped": True, "reason": "missing_fields"}

                media_info = await _process_media_url(media_url)
                logger.info(
                    "Webhook media | phone=%s conv=%s type=%s ct=%s summary=%r",
                    phone, conv_id,
                    media_info.get("media_type", ""),
                    media_info.get("media_content_type", ""),
                    media_info.get("media_summary", "")[:120],
                )

                loop = asyncio.get_event_loop()
                incoming = IncomingDataCrazyMessage(
                    message_id=f"media-{phone}-{loop.time()}",
                    from_number=phone,
                    sender_name=name or None,
                    conversation_id=conv_id,
                    text=media_info.get("synthetic_text", "[lead enviou uma mídia]"),
                    raw_payload=payload,
                    external_id=lead_id,
                    media_type=media_info.get("media_type", ""),
                    media_url=media_info.get("media_url", ""),
                    media_content_type=media_info.get("media_content_type", ""),
                    media_summary=media_info.get("media_summary", ""),
                    media_synthetic_text=media_info.get("synthetic_text", ""),
                )

                if incoming.message_id in _dc_processed_message_ids:
                    return {"success": True, "skipped": True, "reason": "already_processed"}

                _dc_processed_message_ids.add(incoming.message_id)
                asyncio.create_task(message_buffer.add(incoming, _handle_datacrazy_message))
                return {"success": True}

            # ── Format A: flat fields (phone / lead_id / contactId / conversation_id / body) ──
            if "phone" in payload or "conversation_id" in payload:
                phone = _clean_id(str(payload.get("phone") or payload.get("contactId") or ""))
                lead_id = _clean_id(str(payload.get("lead_id") or ""))
                conv_id = _clean_id(str(payload.get("conversation_id") or ""))
                body = str(payload.get("body") or "").strip()
                name = str(payload.get("name") or "").strip()

                if not phone or not conv_id or not body:
                    logger.warning("Webhook Format A: missing required fields phone=%s conv=%s body=%s", phone, conv_id, body[:30])
                    return {"success": True, "skipped": True, "reason": "missing_fields"}

                media_info = None
                if body.startswith("http://") or body.startswith("https://"):
                    try:
                        media_info = await _process_media_url(body)
                        body = media_info.get("synthetic_text", body)
                        logger.info(
                            "Webhook Format A/C media | phone=%s conv=%s type=%s ct=%s summary=%r",
                            phone, conv_id,
                            media_info.get("media_type", ""),
                            media_info.get("media_content_type", ""),
                            media_info.get("media_summary", "")[:120],
                        )
                    except Exception as exc:
                        logger.warning("Webhook Format A/C media processing failed: %s", exc)

                loop = asyncio.get_event_loop()
                incoming = IncomingDataCrazyMessage(
                    message_id=f"webhook-{phone}-{loop.time()}",
                    from_number=phone,
                    sender_name=name or None,
                    conversation_id=conv_id,
                    text=body,
                    raw_payload=payload,
                    external_id=lead_id,
                    media_type=(media_info or {}).get("media_type", ""),
                    media_url=(media_info or {}).get("media_url", ""),
                    media_content_type=(media_info or {}).get("media_content_type", ""),
                    media_summary=(media_info or {}).get("media_summary", ""),
                    media_synthetic_text=(media_info or {}).get("synthetic_text", ""),
                )

                if incoming.message_id in _dc_processed_message_ids:
                    logger.info("Webhook Format A | message already processed (id=%s)", incoming.message_id[:20])
                    return {"success": True, "skipped": True, "reason": "already_processed"}

                logger.info("Webhook Format A | phone=%s lead_id=%s conv=%s body=%s", phone, lead_id, conv_id, body[:50])
                _dc_processed_message_ids.add(incoming.message_id)
                asyncio.create_task(message_buffer.add(incoming, _handle_datacrazy_message))
                return {"success": True}

            # ── Format B: standard conversation/message objects ────────────────
            conv = payload.get("conversation", payload)
            msg = payload.get("message", payload)
            incoming = parse_datacrazy_api_message(conv, msg)
            if incoming is None:
                return {"success": True, "skipped": True}

            media_url = _extract_media_url(payload)
            if media_url and not getattr(incoming, "media_url", ""):
                media_info = await _process_media_url(media_url)
                incoming.text = media_info.get("synthetic_text", incoming.text)
                incoming.media_type = media_info.get("media_type", "")
                incoming.media_url = media_info.get("media_url", "")
                incoming.media_content_type = media_info.get("media_content_type", "")
                incoming.media_summary = media_info.get("media_summary", "")
                incoming.media_synthetic_text = media_info.get("synthetic_text", "")
                logger.info(
                    "Webhook Format B media | session=%s type=%s ct=%s summary=%r",
                    incoming.from_number,
                    incoming.media_type,
                    incoming.media_content_type,
                    incoming.media_summary[:120],
                )

            if incoming.message_id in _dc_processed_message_ids:
                return {"success": True, "skipped": True, "reason": "already_processed"}

            _dc_processed_message_ids.add(incoming.message_id)
            asyncio.create_task(message_buffer.add(incoming, _handle_datacrazy_message))
            return {"success": True}
    except json.JSONDecodeError:
        pass

    # Try DataCrazy custom format:
    # {externalId, name, phone, conversationId, body}
    try:
        content = raw_text.strip()
        if content.startswith('{') and content.endswith('}'):
            content = content[1:-1].strip()

        content = content.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')

        parts = [p.strip() for p in content.split(',')]
        if len(parts) >= 5:
            external_id = parts[0].strip().strip('{}"\' ')
            name = parts[1].strip().strip('{}"\' ')
            phone = parts[2].strip().strip('{}"\' ')
            conv_id = parts[3].strip().strip('{}"\' ')
            body = ','.join(parts[4:]).strip().strip('{}"\' ')

            # ── Auto-reply / system message filter ──
            import re as _re

            # Strip UUID prefix that DataCrazy puts before the real message text.
            # Format C raw body: "{ext_id},{name},{phone},{conv_id},{ext_id}\n{real message}"
            # After CSV split, body = "{ext_id}\n{real message}" — the UUID is NOT part of the
            # user's message, it's the external_id repeated as a delimiter.
            _UUID_STRIP = _re.match(
                r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[\s,;\n]+(.*)',
                body, _re.DOTALL,
            )
            if _UUID_STRIP:
                _original_body = body
                body = _UUID_STRIP.group(1).strip()
                logger.info('Webhook Format C | stripped UUID prefix from body phone=%s original=%r cleaned=%r', phone, _original_body[:80], body[:80])

            _AUTO_REPLY_PATTERNS = [
                r'(?i)agradecemos sua mensagem',
                r'(?i)não estamos disponíveis no momento',
                r'(?i)entraremos em contato assim que possível',
                r'(?i)away.?message',
                r'(?i)out of office',
                r'(?i)mensagem automática',
                r'(?i)this is an automated',
            ]
            for _pat in _AUTO_REPLY_PATTERNS:
                if _re.search(_pat, body):
                    logger.info('Webhook Format C | auto_reply_detected pattern=%s phone=%s body=%r', _pat, phone, body[:120])
                    return {'success': True, 'skipped': 'auto_reply_pattern'}

            # Detect media URLs from DataCrazy in body and process them with the multimodal model.
            if "datacrazy" in body.lower() and ("whatsapp-attachments" in body or any(t in body.lower() for t in ("audio", "image", "sticker", "webp", "jpeg", "jpg", "png"))):
                logger.info("Webhook Format C | media URL detected in body, analyzing with multimodal model...")
                media_info = await _process_media_url(body)
                logger.info("Webhook Format C | analyzed: %r", media_info.get("synthetic_text", "")[:120])
                body = media_info.get("synthetic_text") or media_info.get("media_summary") or body

            # Create a simulated incoming message
            loop = asyncio.get_event_loop()
            incoming = IncomingDataCrazyMessage(
                message_id=f"webhook-{phone}-{loop.time()}",
                from_number=phone,
                sender_name=name,
                conversation_id=conv_id,
                text=body,
                raw_payload={"custom_format": parts},
                external_id=external_id,
            )

            logger.info("Webhook Format C | phone=%s conv=%s body=%r", phone, conv_id, body[:80])
            asyncio.create_task(message_buffer.add(incoming, _handle_datacrazy_message))
            return {"success": True}
    except Exception as exc:
        logger.warning("Failed to parse custom webhook format: %s | body=%s", exc, raw_text[:200])

    raise HTTPException(status_code=400, detail="Invalid payload format")


async def _cleanup_processed_ids() -> None:
    """Limit the size of processed message IDs set to prevent memory growth."""
    global _dc_processed_message_ids
    if len(_dc_processed_message_ids) > 10000:
        _dc_processed_message_ids = set(list(_dc_processed_message_ids)[-5000:])


async def _send_reply(msg: IncomingDataCrazyMessage, reply: str) -> None:
    """Send a plain-text reply via DataCrazy API — only used for /flush confirmations."""
    conv_id = msg.conversation_id.strip().replace('\\n', '').replace('\\r', '').replace('\n', '').replace('\r', '').replace(' ', '')
    url = f"{DATACRAZY_BASE_URL}/api/v1/conversations/{conv_id}/messages"
    payload = {"body": reply}
    headers = {
        "Authorization": f"Bearer {DATACRAZY_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        logger.error("_send_reply | failed to send reply: %s", exc)


async def _handle_datacrazy_message(msg: IncomingDataCrazyMessage) -> None:
    session_id = bridge.session_id_for(msg)
    session_lock = _get_session_lock(session_id)

    async with session_lock:
        tx = log_store.new_transaction(session_id, msg.from_number, msg.text)
        try:
            logger.info("HANDLE | session=%s from=%s text=%r (len=%d)", session_id, msg.from_number, msg.text[:80], len(msg.text))
            log_store.log_event("incoming_message", {"message_id": msg.message_id, "text": msg.text[:200]})

            # ── Auto-resume: if lead is paused, unpause on incoming message ──
            import app.follow_up_state as fus
            if fus.get_flag(session_id, "paused"):
                fus.update_many(session_id, {"paused": 0})
                logger.info("HANDLE | session=%s AUTO-RESUME (paused=0)", session_id)
                log_store.log_event("auto_resume", {"session_id": session_id})

            # ── /flush command ────────────────────────────────────────────────
            # Check each line for /flush (message buffer may combine multiple messages)
            lines = msg.text.strip().split("\n")
            has_flush = any(line.strip().lower().startswith("/flush") for line in lines)
            if has_flush:
                logger.info("HANDLE | /flush command detected — flushing session %s", session_id)
                _flush_session(msg.from_number)
                reply = "Sessão apagada. Próxima mensagem começa do zero."
                logger.info("HANDLE | /flush result: reply=%r", reply)
                await _send_reply(msg, reply)
                log_store.log_event("flush_command", {"session_id": session_id})
                log_store.complete_transaction(reply)
                return

            # ── Agent processes the message and executes tools ────────────────
            logger.info("HANDLE | calling bridge.generate_reply...")
            log_store.log_event("agent_processing", {"session_id": session_id})
            reply = await bridge.generate_reply(msg)
            logger.info("HANDLE | agent reply: %s", reply[:120] if reply else "(empty)")
            log_store.log_event("agent_reply", {"reply": reply[:500] if reply else "(empty)"})
            log_store.complete_transaction(reply or "")

            # If the LLM returned text but no message-sending tools were called,
            # send the reply to the lead manually (e.g. when only set_lead_info was called)
            if reply and reply.strip():
                logger.info("HANDLE | sending LLM text reply to lead: %r", reply[:100])
                await _send_reply(msg, reply)

            # ── Update follow-up tracking (AFTER Agno saves session) ─────────
            await _reset_follow_up(session_id)
            logger.info("HANDLE | follow-up reset for session=%s", session_id)

            if not reply or not reply.strip():
                logger.warning("HANDLE | agent returned EMPTY reply for text=%r", msg.text[:80])

        except Exception as exc:
            logger.error("Failed to handle message %s: %s", msg.message_id, exc, exc_info=True)
            log_store.fail_transaction(str(exc))
            import app.error_log as error_log
            error_log.record(
                session_id=session_id,
                from_number=msg.from_number,
                tool_name="agent_flow",
                exc=exc,
                context={"message_id": msg.message_id, "text": msg.text[:200]},
            )


def _flush_session(from_number: str) -> bool:
    """Remove session from in-memory pool, SQLite, and follow_up_state."""
    session_id = f"vanessa-wa-{from_number}"
    logger.info("FLUSH | attempting to flush session=%s", session_id)
    found = bridge.flush_agent(session_id)
    logger.info("FLUSH | in-memory flush result: %s", found)

    # Remove from SQLite
    import sqlite3
    try:
        conn = sqlite3.connect(SESSION_DB_PATH)
        cur = conn.execute("DELETE FROM agno_sessions WHERE session_id = ?", (session_id,))
        if cur.rowcount > 0:
            found = True
            logger.info("FLUSH | deleted %d row(s) from SQLite", cur.rowcount)
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("FLUSH | sqlite error: %s", exc)

    # Remove from follow_up_state table
    try:
        import app.follow_up_state as fus
        fus.delete_state(session_id)
        logger.info("FLUSH | deleted follow_up_state for %s", session_id)
    except Exception as exc:
        logger.warning("FLUSH | follow_up_state delete error: %s", exc)

    return found


# ── DataCrazy polling loop ────────────────────────────────────────────────────

async def _datacrazy_polling_loop() -> None:
    """Poll DataCrazy conversations for new incoming messages."""
    logger.info("Starting DataCrazy polling loop...")
    headers = {
        "Authorization": f"Bearer {DATACRAZY_API_TOKEN}",
        "Content-Type": "application/json",
    }

    while True:
        now = asyncio.get_event_loop().time()
        if now < _dc_rate_limited_until:
            sleep_secs = _dc_rate_limited_until - now
            logger.info("Rate limit active. Sleeping %.0f seconds...", sleep_secs)
            await asyncio.sleep(sleep_secs)
            continue
        try:
            await _poll_once(headers)
        except Exception as exc:
            logger.error("DataCrazy polling error: %s", exc)
        await asyncio.sleep(_dc_polling_interval)


async def _poll_once(headers: dict[str, str]) -> None:
    url = f"{DATACRAZY_BASE_URL}/api/v1/conversations"
    params = {
        "instanceId": DATACRAZY_INSTANCE_ID,
        "status": "open",
        "limit": 20,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    conversations = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(conversations, list):
        return

    logger.info("POLL | found %d conversations", len(conversations))

    # Debug: show all conversation contactIds
    for c in conversations:
        contact = c.get("contact") or {}
        cid = contact.get("contactId", "")
        name = contact.get("name", "")
        logger.info("POLL | conv=%s contactId=%s name=%s", c.get("id", ""), cid, name)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for conv in conversations:
            conv_id = conv.get("id", "")
            if not conv_id:
                continue

            # Fetch messages for this conversation
            msgs_url = f"{DATACRAZY_BASE_URL}/api/v1/conversations/{conv_id}/messages"
            try:
                msgs_resp = await client.get(msgs_url, headers=headers)
                if msgs_resp.status_code == 429:
                    logger.warning("Rate limited by DataCrazy. Pausing polling for 30s.")
                    global _dc_rate_limited_until
                    _dc_rate_limited_until = asyncio.get_event_loop().time() + 30
                    break
                msgs_resp.raise_for_status()
                msgs_data = msgs_resp.json()
            except Exception as exc:
                logger.warning("Failed to fetch messages for conv %s: %s", conv_id, exc)
                continue

            messages = msgs_data.get("data", []) if isinstance(msgs_data, dict) else msgs_data
            if not isinstance(messages, list):
                continue

            logger.info("POLL | conv=%s | %d messages", conv_id, len(messages))

            for msg in messages:
                msg_id = msg.get("id", "")
                received = msg.get("received")
                body = msg.get("body", "")[:60]

                if not msg_id:
                    logger.info("POLL | msg skipped: no id")
                    continue
                if msg_id in _dc_processed_message_ids:
                    logger.info("POLL | msg=%s already processed", msg_id[:12])
                    continue

                incoming = parse_datacrazy_api_message(conv, msg)
                if incoming is None:
                    logger.info("POLL | msg=%s parse returned None (received=%s body=%r)", msg_id[:12], received, body)
                    _dc_processed_message_ids.add(msg_id)
                    continue

                logger.info("POLL | msg=%s | from=%s | body=%r → dispatching", msg_id[:12], incoming.from_number, incoming.text[:60])
                _dc_processed_message_ids.add(msg_id)
                asyncio.create_task(message_buffer.add(incoming, _handle_datacrazy_message))

            # Small delay between conversations to avoid rate limits
            await asyncio.sleep(0.3)

    await _cleanup_processed_ids()


# ── Pause follow-up via DataCrazy tag (agente_suporte_ia) ───────────────────

@app.post("/vfo/webhooks/pause-lead")
@app.post("/vfo-2/webhooks/pause-lead")
async def pause_lead_webhook(request: Request):
    """
    Webhook called by DataCrazy automations when tag 'pausa_IA' is added.
    Always pauses follow-up scheduling for the lead.

    Accepts DataCrazy custom format:
    { externalId, name, phone, conversationId, body }
    """
    try:
        raw = (await request.body()).decode("utf-8").strip()
        logger.info("pause_lead | raw body: %s", raw[:300])

        # Normalize: replace escaped \n and real newlines with spaces
        normalized = raw.replace("\\n", "\n").replace("\r", "")
        # Collapse to single line for easier parsing
        flat = " ".join(normalized.split())

        phone = ""
        conv_id = ""

        # Try JSON first
        try:
            payload = json.loads(raw)
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                phone = str(payload.get("leadPhone") or payload.get("phone") or "").strip()
                conv_id = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
        except json.JSONDecodeError:
            pass

        # Fallback: DataCrazy custom format — use regex to find phone (digits, 10-15 chars)
        if not phone:
            import re
            # Remove the outer braces and split by comma
            inner = flat.strip("{} ")
            parts = [p.strip().strip("{}\"' ") for p in inner.split(",")]
            # Find the phone: a string of 10-15 digits
            for part in parts:
                digits = re.sub(r"\D", "", part)
                if 10 <= len(digits) <= 15:
                    phone = digits
                    break
            # Find conversationId: looks like a hex string or mongo ObjectId
            for part in parts:
                clean = part.strip()
                if len(clean) >= 20 and re.match(r"^[a-f0-9]+$", clean, re.I):
                    conv_id = clean
                    break

        if not phone:
            logger.warning("pause_lead | no phone found in payload")
            raise HTTPException(status_code=400, detail="Could not extract phone from payload")

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("pause_lead | parse error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    session_id = f"vanessa-wa-{phone}"
    import app.follow_up_state as fus
    fus.update_many(session_id, {"paused": 1})
    logger.info("pause_lead | session=%s phone=%s conv=%s PAUSED", session_id, phone, conv_id)
    return {"status": "paused", "session_id": session_id, "phone": phone}

# ═══════════════════════════════════════════════════════════════════════════════
# Payment webhook — Kiwify + Cakto
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_lead(src: str) -> tuple[str, str, str]:
    """Resolve lead phone, session_id and conversation_id from src (external_id).
    Lookup order: 1) payment_links table, 2) agno_sessions.
    Returns (phone, session_id, conversation_id) or ("", "", "") if not found."""
    import app.follow_up_state as fus

    # 1) payment_links — fastest, always populated when link was sent via our agent
    pl = fus.get_payment_link_by_lead(src)
    if pl and pl.get("phone"):
        phone = pl["phone"]
        session_id = pl.get("session_id", f"vanessa-wa-{phone}")
        # Get conversation_id from follow_up_state
        state = fus.get_state(session_id)
        conv_id = state.get("conversation_id", "")
        if conv_id:
            return phone, session_id, conv_id

    # 2) Fallback: agno_sessions — search by external_id in session_data
    import sqlite3, json
    conn = sqlite3.connect(SESSION_DB_PATH)
    rows = conn.execute(
        "SELECT session_id, session_data FROM agno_sessions WHERE session_data IS NOT NULL"
    ).fetchall()
    conn.close()
    for row in rows:
        try:
            data = json.loads(row[1])
            while isinstance(data, str):
                data = json.loads(data)
            state = data.get("session_state", {})
            if state.get("external_id") == src:
                phone = state.get("from_number", "")
                conv_id = state.get("conversation_id", "")
                if phone:
                    return phone, row[0], conv_id
        except (json.JSONDecodeError, TypeError):
            continue

    return "", "", ""


@app.post("/vfo/webhooks/payment")
@app.post("/vfo-2/webhooks/payment")
async def payment_webhook(request: Request):
    """Recebe webhooks de pagamento da Kiwify e Cakto.
    Detecta a origem pelo formato do payload e processa adequadamente.
    Busca lead SEMPRE por src (external_id)."""
    try:
        raw = await request.body()
        body_text = raw.decode("utf-8", errors="replace")
        logger.info("payment_webhook | raw body: %s", body_text[:500])

        # Try JSON
        try:
            payload = await request.json()
        except Exception:
            payload = {}
            form = await request.form()
            if form:
                payload = dict(form)

        if not payload:
            logger.warning("payment_webhook | empty payload")
            raise HTTPException(status_code=400, detail="Empty payload")

        # ── Detect origin: Kiwify vs Cakto ──
        is_kiwify = "order_id" in payload or "order_status" in payload or "product_name" in payload
        is_cakto = "event" in payload or "purchase" in payload or "transaction_id" in payload

        if not is_kiwify and not is_cakto:
            if "kiwify" in body_text.lower():
                is_kiwify = True
            elif "cakto" in body_text.lower():
                is_cakto = True
            else:
                logger.warning("payment_webhook | could not detect origin: %s", str(payload)[:200])
                return {"status": "ignored", "reason": "unknown_origin"}

        import app.follow_up_state as fus

        if is_kiwify:
            return await _handle_kiwify_payment(payload, fus)
        else:
            return await _handle_cakto_payment(payload, fus)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("payment_webhook | error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


async def _handle_kiwify_payment(payload: dict, fus) -> dict:
    """Processa webhook da Kiwify. Busca lead por src."""
    order_status = str(payload.get("order_status", "")).lower()
    order_id = str(payload.get("order_id", ""))
    src = str(payload.get("src", ""))
    full_name = str(payload.get("full_name", ""))
    product_name = str(payload.get("product_name", ""))
    payment_method = str(payload.get("payment_method", ""))
    amount = float(payload.get("price", 0) or payload.get("amount", 0) or 0)

    if not src:
        logger.warning("kiwify_payment | no src in payload, cannot resolve lead")
        return {"status": "error", "reason": "missing_src"}

    # Resolve lead by src
    phone, session_id, conv_id = _resolve_lead(src)
    if not phone:
        logger.warning("kiwify_payment | lead not found for src=%s", src)
        return {"status": "error", "reason": "lead_not_found", "src": src}

    logger.info(
        "kiwify_payment | order=%s status=%s src=%s phone=%s product=%s",
        order_id, order_status, src, phone, product_name,
    )

    if order_status in ("paid", "approved", "confirmed"):
        fus.mark_paid(
            lead_id=src,
            phone=phone,
            order_id=order_id,
            order_status="paid",
            payment_method=payment_method,
            product_name=product_name,
            amount=amount,
        )
        name = full_name.split()[0] if full_name else ""
        await _send_post_payment_message(src, phone, conv_id, name, "parabens")

    elif order_status in ("refunded", "chargeback"):
        fus.mark_refunded(order_id)
        name = full_name.split()[0] if full_name else ""
        await _send_post_payment_message(src, phone, conv_id, name, "refund")

    else:
        logger.info("kiwify_payment | ignoring status=%s", order_status)

    return {"status": "processed", "origin": "kiwify", "order_status": order_status}


async def _handle_cakto_payment(payload: dict, fus) -> dict:
    """Processa webhook da Cakto. Busca lead por src."""
    event = str(payload.get("event", "")).lower()
    order_id = str(payload.get("transaction_id", "") or payload.get("order_id", ""))
    src = str(payload.get("src", "") or payload.get("customer_id", ""))
    full_name = str(payload.get("name", "") or payload.get("customer_name", ""))
    product_name = str(payload.get("product_name", "") or payload.get("product", ""))
    amount = float(payload.get("amount", 0) or payload.get("price", 0) or 0)

    if not src:
        logger.warning("cakto_payment | no src in payload, cannot resolve lead")
        return {"status": "error", "reason": "missing_src"}

    phone, session_id, conv_id = _resolve_lead(src)
    if not phone:
        logger.warning("cakto_payment | lead not found for src=%s", src)
        return {"status": "error", "reason": "lead_not_found", "src": src}

    logger.info(
        "cakto_payment | event=%s order=%s src=%s phone=%s",
        event, order_id, src, phone,
    )

    if event in ("purchase.complete", "purchase.approved", "paid", ""):
        fus.mark_paid(
            lead_id=src,
            phone=phone,
            order_id=order_id,
            order_status="paid",
            product_name=product_name,
            amount=amount,
        )
        name = full_name.split()[0] if full_name else ""
        await _send_post_payment_message(src, phone, conv_id, name, "parabens")

    elif event in ("refund", "refunded", "chargeback"):
        fus.mark_refunded(order_id)
        name = full_name.split()[0] if full_name else ""
        await _send_post_payment_message(src, phone, conv_id, name, "refund")

    else:
        logger.info("cakto_payment | ignoring event=%s", event)

    return {"status": "processed", "origin": "cakto", "event": event}


async def _send_post_payment_message(
    src: str, phone: str, conv_id: str, name: str, msg_type: str
) -> None:
    """Envia mensagem pós-pagamento via DataCrazy API."""
    try:
        from app.datacrazy_automation import DataCrazyAutomationClient

        if not conv_id:
            logger.warning("_send_post_payment_message | no conversation_id for src=%s phone=%s", src, phone)
            return

        greeting = f"{name}, " if name else ""

        if msg_type == "parabens":
            msg = (
                f"{greeting}parabéns! 🎉\n\n"
                f"Você acabou de dar o primeiro passo para transformar a sua vida!\n\n"
                f"Para os próximos passos e para você ter acesso ao treinamento, "
                f"fala com meu time de suporte aqui:\n\n"
                f"https://wa.me/558599549121?text=oiii%20Van%2C%20j%C3%A1%20sou%20aluna%2C%20gostaria%20de%20ajuda\n\n"
                f"Bora pra cima! ✨"
            )
        elif msg_type == "refund":
            msg = (
                f"{greeting}tudo bem? Vi que você solicitou o reembolso.\n\n"
                f"Se precisar de qualquer ajuda ou tiver alguma dúvida, "
                f"fala com meu time de suporte:\n\n"
                f"https://wa.me/558599549121?text=oiii%20Van%2C%20tenho%20uma%20d%C3%BAvida%20sobre%20meu%20pedido"
            )
        else:
            return

        automation = DataCrazyAutomationClient()
        await automation.send_text_message(conv_id, msg)
        await automation.aclose()

        # Mark session as purchased
        import app.follow_up_state as fus2
        session_id = f"vanessa-wa-{phone}"
        fus2.set_flag(session_id, "is_purchased", True)
        logger.info("_send_post_payment_message | %s sent to src=%s phone=%s conv=%s", msg_type, src, phone, conv_id)

    except Exception as exc:
        logger.error("_send_post_payment_message | failed for src=%s phone=%s: %s", src, phone, exc, exc_info=True)
