from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from app import follow_up_state as fus

logger = logging.getLogger("vanessa.flow")

# ── Technical error detection ────────────────────────────────────────────────
# Patterns that indicate an API/model error that MUST NEVER be sent to the lead.
_ERROR_PATTERNS = re.compile(
    r"quota.exhausted|rate.limit|429|5\d{2}\s|timeout|connection.refused|"
    r"overloaded|server.error|bad.gateway|service.unavailable|"
    r"model.*not.*found|invalid.*api.*key|insufficient.*quota|"
    r"\berror\b.*\[|\[.*\d{3}\].*:|traceback|exception",
    re.IGNORECASE,
)

_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 3.0  # seconds


def _is_technical_error(text: str) -> bool:
    """Return True if `text` looks like an API/model error, not a real reply."""
    if not text:
        return False
    # Very short responses that contain error patterns
    if len(text) < 500 and _ERROR_PATTERNS.search(text):
        return True
    # Stacktrace-like content
    if "Traceback" in text or "Exception:" in text:
        return True
    return False

# Tools that actually send messages to the lead (vs internal tools like set_lead_info)
_SENDS_MESSAGE_TOOLS = {
    "send_intro", "send_text_message", "send_payment_link", "send_challenge_link",
    "send_cakto_link", "present_price", "ask_motivation", "pause_lead",
    "trigger_experiencia", "trigger_mentoria", "trigger_comecando_do_zero",
    "trigger_automation_1", "trigger_automation_2",
    "trigger_precisa_computador", "trigger_tempo_resultados", "trigger_tempo_livre",
    "trigger_experiencias_ruins", "trigger_tem_medo", "trigger_tem_profissao",
    "trigger_outro_pais", "trigger_e_mae", "trigger_faz_faculdade",
    "trigger_e_crista", "trigger_como_sei_seguro", "trigger_preciso_pagar",
    "trigger_vai_ver",
}

# Business hours: 07:00 - 23:00 America/Fortaleza (UTC-3)
_BIZ_START_UTC = 10   # 07:00 Fortaleza = 10:00 UTC
_BIZ_END_UTC = 2      # 23:00 Fortaleza = 02:00 UTC (next day)

# Response delay range (seconds)
_DELAY_MIN = 110
_DELAY_MAX = 130


def _is_within_business_hours() -> bool:
    """Check if current time is within 08:00-23:00 Fortaleza (UTC-3)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour = now.hour
    # 08:00 Fortaleza = 11:00 UTC, 23:00 Fortaleza = 02:00 UTC next day
    if _BIZ_START_UTC <= hour <= 23:
        return True
    if 0 <= hour < _BIZ_END_UTC:
        return True
    return False


@dataclass
class IncomingDataCrazyMessage:
    message_id: str
    from_number: str       # E.164 without +: "5511999999999"
    sender_name: str | None
    conversation_id: str
    text: str
    raw_payload: dict[str, Any]
    external_id: str = ""  # DataCrazy contact externalId (UUID)
    media_type: str = ""
    media_url: str = ""
    media_content_type: str = ""
    media_summary: str = ""
    media_synthetic_text: str = ""


def parse_datacrazy_api_message(
    conversation: dict, message: dict
) -> IncomingDataCrazyMessage | None:
    """
    Parse a message returned from DataCrazy API
    (GET /api/v1/conversations/{id}/messages) into an incoming message object.

    Only processes messages that were RECEIVED from the user (not sent by us).
    """
    # Skip messages sent by the system/agent
    if not message.get("received"):
        return None

    body = str(message.get("body") or "").strip()
    attachments = message.get("attachments") or []
    first_attachment = attachments[0] if attachments else {}

    media_url = str(first_attachment.get("url") or "").strip()
    media_content_type = str(first_attachment.get("contentType") or first_attachment.get("mimeType") or "").strip().lower()
    media_type = str(first_attachment.get("type") or message.get("type") or "").strip().lower()

    # Some media messages have an empty body; accept them if media metadata exists.
    if not body and not media_url:
        return None

    contact = conversation.get("contact") or {}
    from_number = str(contact.get("contactId", ""))
    sender_name = contact.get("name")

    return IncomingDataCrazyMessage(
        message_id=message.get("id", ""),
        from_number=from_number,
        sender_name=sender_name,
        conversation_id=conversation.get("id", ""),
        text=body or media_url,
        raw_payload={"conversation": conversation, "message": message},
        media_type=media_type,
        media_url=media_url,
        media_content_type=media_content_type,
    )


class AgentRuntime:
    """Thread-safe pool of Agent instances keyed by session_id."""

    def __init__(self, agent_factory: Callable[..., Any]) -> None:
        self._factory = agent_factory
        self._agents: dict[str, Any] = {}
        self._lock = Lock()

    def get_agent(self, session_id: str, from_number: str = "", conversation_id: str = "") -> Any:
        with self._lock:
            if session_id not in self._agents:
                self._agents[session_id] = self._factory(
                    session_id=session_id,
                    from_number=from_number,
                    conversation_id=conversation_id,
                )
            return self._agents[session_id]

    def flush(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._agents:
                del self._agents[session_id]
                return True
            return False


class DataCrazyBridge:
    def __init__(self, agent_factory: Callable[..., Any]) -> None:
        self._runtime = AgentRuntime(agent_factory)

    def session_id_for(self, msg: IncomingDataCrazyMessage) -> str:
        return f"vanessa-wa-{msg.from_number}"

    async def generate_reply(self, msg: IncomingDataCrazyMessage) -> str:
        session_id = self.session_id_for(msg)
        agent = self._runtime.get_agent(
            session_id=session_id,
            from_number=msg.from_number,
            conversation_id=msg.conversation_id,
        )
        # Ensure conversation_id, external_id and media context are always up to date
        agent.session_state["conversation_id"] = msg.conversation_id
        if msg.external_id:
            agent.session_state["external_id"] = msg.external_id

        agent.session_state["last_media_type"] = msg.media_type or ""
        agent.session_state["last_media_url"] = msg.media_url or ""
        agent.session_state["last_media_content_type"] = msg.media_content_type or ""
        agent.session_state["last_media_summary"] = msg.media_summary or ""
        agent.session_state["last_media_synthetic_text"] = msg.media_synthetic_text or ""
        if msg.media_type:
            agent.session_state["last_media_received_at"] = datetime.now(timezone.utc).isoformat()

        # ── Reset double-send guard for this turn ──
        agent.session_state["_text_msg_sent_this_turn"] = False
        agent.session_state["_text_msg_call_count"] = 0

        # ── Paused lead gate (tag agente_suporte_ia) ──
        fu_state_pre = fus.get_state(session_id)
        if fu_state_pre.get("paused"):
            logger.info("generate_reply | lead is paused (agente_suporte_ia), skipping: session=%s", session_id)
            return ""

        # ── Business hours gate (07:00-23:00 Fortaleza) ──
        if not _is_within_business_hours():
            fus.ensure_row(session_id)
            fus.update_many(session_id, {
                "pending_response": 1,
                "pending_message_text": msg.text[:500],
                "conversation_id": msg.conversation_id,
                "external_id": msg.external_id or "",
                "sender_name": msg.sender_name or "",
            })
            logger.info(
                "generate_reply | outside business hours, saved as pending: session=%s text=%r",
                session_id, msg.text[:80],
            )
            return ""

        # ── Response delay (2 min) ──
        # Always delay to simulate human response time
        delay_secs = random.uniform(_DELAY_MIN, _DELAY_MAX)
        logger.info("generate_reply | delaying %.0fs for session=%s", delay_secs, session_id)
        await asyncio.sleep(delay_secs)

        # Update last_lead_message_at and conversation_id after delay
        from datetime import datetime, timezone
        fus.ensure_row(session_id)
        fus.set_value(session_id, "last_lead_message_at", datetime.now(timezone.utc).isoformat())
        fus.set_value(session_id, "conversation_id", msg.conversation_id)
        if msg.external_id:
            fus.set_value(session_id, "external_id", msg.external_id)
        if msg.sender_name:
            fus.set_value(session_id, "sender_name", msg.sender_name)
        # Clear pending flag if it was set
        fu_state = fus.get_state(session_id)
        if fu_state.get("pending_response"):
            fus.set_value(session_id, "pending_response", 0)
            fus.set_value(session_id, "pending_message_text", "")

        # ── Sync follow_up_state → agent session_state ──
        # Ensures agent reads the REAL follow-up progress from the scheduler,
        # not stale values from Agno's session_state.
        _SYNC_KEYS = [
            "follow_up_flow", "follow_up_flow_count",
            "follow_up_flow_started_at", "follow_up_flow_anchor",
            "follow_up_expired",
            "automation_1_sent", "automation_2_sent", "experiencia_sent",
            "follow_1_1_sent", "follow_1_2_sent", "follow_1_3_sent", "follow_1_4_sent",
            "follow_2_1_sent", "follow_2_2_sent", "follow_2_3_sent",
            "follow_3_1_sent", "follow_3_2_sent", "follow_3_3_sent",
            "lead_name", "lead_profile", "lead_context",
            "funnel_phase", "is_purchased", "payment_tier_sent",
            "motivation_question_sent", "comecando_do_zero_sent",
            "follow_janela_24h_sent",
        ]
        for _key in _SYNC_KEYS:
            _val = fu_state.get(_key)
            if _val is not None and _val != "" and _val != 0:
                agent.session_state[_key] = _val

        import time
        start = time.monotonic()
        logger.info("generate_reply | calling agent.arun with text=%r", msg.text[:100])

        # ── Retry loop with backoff for transient LLM errors (429/5xx) ──
        result = None
        last_exc = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                result = await agent.arun(msg.text, session_state=agent.session_state)
                # Check if the model returned an error as content
                raw_content = getattr(result, "content", "") or ""
                if _is_technical_error(raw_content):
                    logger.warning(
                        "generate_reply | attempt %d/%d: technical error in content: %r",
                        attempt + 1, _MAX_RETRIES + 1, raw_content[:200],
                    )
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.info("generate_reply | retrying in %.1fs...", delay)
                        await asyncio.sleep(delay)
                        continue
                    # All retries exhausted — return empty, never leak to lead
                    logger.error("generate_reply | all retries exhausted, returning empty")
                    return ""
                break  # success — exit retry loop
            except Exception as exc:
                last_exc = exc
                logger.warning("generate_reply | attempt %d/%d failed: %s", attempt + 1, _MAX_RETRIES + 1, exc)
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                    logger.info("generate_reply | retrying in %.1fs...", delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("generate_reply | all retries exhausted with exception: %s", exc, exc_info=True)
                    return ""

        latency_ms = int((time.monotonic() - start) * 1000)

        # Check if tools were called
        tool_calls = []
        if hasattr(result, "tools"):
            tool_calls = result.tools or []
        if hasattr(result, "content") and result.content:
            logger.info("generate_reply | LLM content: %r", result.content[:200])
        else:
            logger.info("generate_reply | LLM content is EMPTY")
        logger.info("generate_reply | tool_calls_count=%d latency_ms=%d", len(tool_calls), latency_ms)
        logger.info("generate_reply | result type=%s, has tools=%s, tools value=%s", 
                    type(result).__name__, hasattr(result, "tools"), str(tool_calls)[:200])

        # Log LLM usage
        try:
            import app.llm_usage_log as llm_log
            usage = None
            if hasattr(result, "metrics") and result.metrics:
                usage = result.metrics
            elif hasattr(result, "usage"):
                usage = result.usage

            if usage:
                llm_log.save(
                    session_id=session_id,
                    model=getattr(agent.model, "id", "unknown"),
                    input_tokens=getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0),
                    cache_read_tokens=getattr(usage, "cache_read_tokens", 0),
                    cache_write_tokens=getattr(usage, "cache_write_tokens", 0),
                    total_tokens=getattr(usage, "total_tokens", 0),
                    cost_usd=getattr(usage, "cost", 0) or getattr(usage, "cost_usd", None),
                    latency_ms=latency_ms,
                )
        except Exception as exc:
            logger.warning("llm_usage_log | failed to save: %s", exc)

        # If tools were called, they already sent messages via DataCrazy API.
        # Return empty string to avoid sending the LLM's text as a duplicate message.
        # ── DOUBLE-SEND MONITOR: check if guard blocked a second call ──
        call_count = agent.session_state.get("_text_msg_call_count", 0)
        if call_count > 1:
            logger.warning(
                "generate_reply | DOUBLE-SEND ATTEMPT BLOCKED — send_text_message called %d times this turn",
                call_count,
            )
        if tool_calls:
            # Only suppress LLM text if a message-sending tool was actually called
            sent_message = any(
                getattr(tc, "tool_name", "") in _SENDS_MESSAGE_TOOLS
                for tc in tool_calls
            )
            if sent_message:
                logger.info("generate_reply | message-sending tools called, returning empty to avoid duplicate")
                return ""
            else:
                # Internal tools only (set_lead_info, get_lead_info) — return LLM text as reply
                reply = result.content if hasattr(result, "content") and result.content else ""
                logger.info("generate_reply | internal-only tools, returning LLM text: %r", reply[:100])
                return reply

        # ── Empty reply fallback ──
        final_content = result.content if hasattr(result, "content") else str(result)
        if not final_content or not final_content.strip():
            logger.warning("generate_reply | empty LLM content, attempting retry with simplified prompt: session=%s", session_id)
            try:
                retry_result = await agent.arun(
                    f"O lead enviou uma mensagem mas não recebi uma resposta adequada. Mensagem do lead: {msg.text[:200]}. Responda de forma natural e breve.",
                    session_state=agent.session_state,
                )
                retry_content = getattr(retry_result, "content", "") or ""
                if retry_content.strip():
                    logger.info("generate_reply | retry succeeded: %r", retry_content[:120])
                    return retry_content
            except Exception as retry_exc:
                logger.warning("generate_reply | retry failed: %s", retry_exc)

            # Retry also empty — send safe fallback message via DataCrazy
            logger.warning("generate_reply | retry also empty, sending fallback message: session=%s", session_id)
            try:
                from app.datacrazy_automation import DataCrazyAutomationClient
                _fallback_client = DataCrazyAutomationClient()
                fallback_msg = "Oi! Pode me mandar de novo? Acho que não chegou direito aqui 😊"
                conv_id = agent.session_state.get("conversation_id", "")
                if conv_id:
                    await _fallback_client.send_text_message(conv_id, fallback_msg)
                    await _fallback_client.aclose()
                    logger.info("generate_reply | fallback message sent to conv=%s", conv_id)
                else:
                    logger.warning("generate_reply | no conversation_id, cannot send fallback")
            except Exception as fb_exc:
                logger.error("generate_reply | fallback send failed: %s", fb_exc)
            return ""

        return final_content

    def flush_agent(self, session_id: str) -> bool:
        return self._runtime.flush(session_id)
