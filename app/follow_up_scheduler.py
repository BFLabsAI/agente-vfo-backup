from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import SESSION_DB_PATH
from app.datacrazy_automation import DataCrazyAutomationClient
from app import follow_up_state as fus
from app.whatsapp_bridge import _is_within_business_hours

logger = logging.getLogger("vanessa.follow_up")

# Load templates (v2 - multi-flow)
_TEMPLATES_PATH = Path(__file__).parent.parent / "data" / "follow_up_templates.json"
_TEMPLATES: dict[str, list[dict[str, Any]]] = {}

# Polling interval (seconds)
_POLL_INTERVAL = 5

# --- Intervalos de PRODUÇÃO (seconds) ---
_INTERVALS = {
    1: {1: 1800, 2: 3600, 3: 7200, 4: 18000},    # 30min, 1h, 2h, 5h
    2: {1: 1800, 2: 7200, 3: 14400},               # 30min, 2h, 4h
    3: {1: 1200, 2: 7200, 3: 10800},               # 20min, 2h, 3h
}

# --- Intervalos de TESTE (seconds) ---
_INTERVALS_TEST = {
    1: {1: 300, 2: 420, 3: 540, 4: 660},  # 5min, 7min, 9min, 11min
    2: {1: 600, 2: 720, 3: 840},           # 10min, 12min, 14min
    3: {1: 300, 2: 420, 3: 540},           # 5min, 7min, 9min
}

# Set to _INTERVALS_TEST for testing, _INTERVALS for production
_ACTIVE_INTERVALS = _INTERVALS


def _load_templates() -> dict[str, list[dict[str, Any]]]:
    global _TEMPLATES
    if not _TEMPLATES:
        with open(_TEMPLATES_PATH, "r", encoding="utf-8") as f:
            _TEMPLATES = json.load(f)
    return _TEMPLATES


def _get_active_sessions() -> list[dict[str, Any]]:
    """
    Query SQLite for all sessions, merging Agno session_data (for conversation
    context like lead_name, conversation_id) with follow_up_state table (for
    flags and tracking — immune to Agno overwrites).
    """
    sessions = []
    all_fus = fus.get_all_states()

    try:
        conn = sqlite3.connect(SESSION_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, session_data FROM agno_sessions WHERE session_data IS NOT NULL"
        ).fetchall()
        conn.close()

        for row in rows:
            session_id = row["session_id"]
            try:
                data = json.loads(row["session_data"])
                while isinstance(data, str):
                    data = json.loads(data)
                if isinstance(data, dict):
                    agno_state = data.get("session_state", {})
                    if isinstance(agno_state, dict):
                        # Start with Agno state (conversation context)
                        merged = dict(agno_state)
                        # Override with follow_up_state table (flags & tracking)
                        fu = all_fus.get(session_id, {})
                        merged.update(fu)
                        sessions.append({"session_id": session_id, "state": merged})
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as exc:
        logger.error("_get_active_sessions | db error: %s", exc)

    # Also include sessions that exist in follow_up_state but not in agno_sessions
    # (edge case: agno session was flushed but follow_up_state wasn't)
    existing_ids = {s["session_id"] for s in sessions}
    for sid, fu in all_fus.items():
        if sid not in existing_ids and fu.get("last_lead_message_at"):
            sessions.append({"session_id": sid, "state": fu})

    return sessions


def _extract_phone(session_id: str) -> str:
    """Extract phone number from session_id like 'vanessa-wa-5581...'."""
    return session_id.replace("vanessa-wa-", "").strip()


def _determine_flow(state: dict) -> int:
    """
    Determina qual fluxo de follow-up o lead deve estar.
    Retorna 1, 2, ou 3.
    """
    if state.get("automation_2_sent"):
        return 3
    # Checar AMBAS as flags: automation_1_sent (agente) E follow_1_4_sent (scheduler)
    # porque Agno pode sobrescrever automation_1_sent quando o agente processa msg
    if state.get("automation_1_sent") or state.get("follow_1_4_sent"):
        return 2
    return 1


def _get_follow_flag_key(flow: int, step: int) -> str:
    """Retorna a chave da flag de envio para um follow específico."""
    return f"follow_{flow}_{step}_sent"


def _is_eligible(state: dict) -> tuple[int, dict] | None:
    """
    Verifica se o lead é elegível para receber um follow-up.
    Retorna (flow_number, template) se elegível, None caso contrário.
    """
    # Pular se comprou ou se link de pagamento já foi enviado
    if state.get("is_purchased"):
        return None
    if state.get("payment_tier_sent", 0):
        return None

    # Pular se follow-up expirou
    if state.get("follow_up_expired"):
        return None

    # Deve ter timestamp de última mensagem
    last_msg = state.get("last_lead_message_at", "")
    if not last_msg:
        return None

    # Parse do timestamp
    try:
        last_dt = datetime.fromisoformat(last_msg)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

    now = datetime.now(timezone.utc)
    elapsed = (now - last_dt).total_seconds()

    # Janela de 24h (última mensagem do lead)
    if elapsed > 86400:
        return None

    # Determinar fluxo atual
    flow = _determine_flow(state)

    # Carregar templates do fluxo
    templates = _load_templates()
    flow_key = f"flow_{flow}"
    flow_templates = templates.get(flow_key, [])

    if not flow_templates:
        return None

    # Contagem atual no fluxo
    count = state.get("follow_up_flow_count", 0)
    current_flow = state.get("follow_up_flow", 0)

    # Calcular time_in_flow (antes de qualquer uso)
    flow_started = state.get("follow_up_flow_started_at", "")

    if flow_started:
        try:
            started_dt = datetime.fromisoformat(flow_started)
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            time_in_flow = (now - started_dt).total_seconds()
        except (ValueError, TypeError):
            time_in_flow = elapsed
    else:
        anchor_str = state.get("follow_up_flow_anchor", "")
        if anchor_str:
            try:
                anchor_dt = datetime.fromisoformat(anchor_str)
                if anchor_dt.tzinfo is None:
                    anchor_dt = anchor_dt.replace(tzinfo=timezone.utc)
                time_in_flow = (now - anchor_dt).total_seconds()
            except (ValueError, TypeError):
                time_in_flow = elapsed
        else:
            time_in_flow = elapsed

    # Se mudou de fluxo, encontrar o primeiro follow não enviado (respeitando delay)
    if current_flow != flow:
        for tpl in flow_templates:
            flag_key = _get_follow_flag_key(flow, tpl["step"])
            if not state.get(flag_key, False):
                required_delay = _ACTIVE_INTERVALS.get(flow, {}).get(
                    tpl["step"],
                    tpl.get("delay_seconds", 60)
                )
                if time_in_flow >= required_delay:
                    return (flow, tpl)
                break  # não elegível ainda — respeitar delay
        return None

    # Já enviou todos do fluxo?
    if count >= len(flow_templates):
        return None

    # Verificar tempo para o próximo follow
    next_template = flow_templates[count]

    # Verificar flag de anti-duplicação: se já foi enviado, pular para o próximo
    flag_key = _get_follow_flag_key(flow, next_template["step"])
    if state.get(flag_key, False):
        # Já enviado — buscar o próximo não enviado
        for tpl in flow_templates[count + 1:]:
            next_flag = _get_follow_flag_key(flow, tpl["step"])
            if not state.get(next_flag, False):
                next_template = tpl
                break
        else:
            # Todos os próximos já foram enviados
            return None

    required_delay = _ACTIVE_INTERVALS.get(flow, {}).get(
        next_template["step"],
        next_template.get("delay_seconds", 60)
    )

    if time_in_flow >= required_delay:
        # Verificar anti-duplicação para automações do fluxo normal
        if flow == 1:
            if next_template["step"] == 1 and (state.get("automation_1_sent") or state.get("experiencia_sent") or state.get("follow_1_1_sent")):
                # Aut.1 ou experiencia já foi enviada pelo agente (mesmo webhook), pular para o próximo
                for tpl in flow_templates[1:]:
                    if not state.get(_get_follow_flag_key(1, tpl["step"]), False):
                        return (flow, tpl)
                return None
            if next_template["step"] == 4 and state.get("automation_1_sent"):
                # Aut.1 já enviada, só enviar texto (remover automação)
                next_template = {**next_template, "automation": None}

        return (flow, next_template)

    return None


def _format_message(template: str, state: dict) -> str:
    """Replace {nome} placeholder with lead name. Remove if empty."""
    # Try lead_name from state (merged: Agno + follow_up_state)
    nome = state.get("lead_name", "").strip()
    if not nome:
        # Fallback: try sender_name from follow_up_state
        nome = state.get("sender_name", "").strip()
    if not nome:
        # Remove "{nome}, " and "{nome} " patterns from the template
        import re
        template = re.sub(r'\{nome\},?\s*', '', template)
        return template.strip()
    return template.replace("{nome}", nome)


async def _send_follow_up(
    session_id: str,
    state: dict,
    flow: int,
    template: dict[str, Any],
    automation_client: DataCrazyAutomationClient,
) -> bool:
    """Send a follow-up message for the given flow."""
    phone = _extract_phone(session_id)
    conversation_id = state.get("conversation_id", "")
    external_id = state.get("external_id", "")
    from_number = state.get("from_number", phone)

    if not conversation_id:
        logger.warning("_send_follow_up | no conversation_id for session=%s", session_id)
        return False

    # Enviar texto (se houver)
    message_text = template.get("message", "")
    if message_text:
        message = _format_message(message_text, state)
        logger.info(
            "_send_follow_up | session=%s flow=%d step=%d msg=%r",
            session_id, flow, template["step"], message[:80],
        )
        result = await automation_client.send_text_message(conversation_id, message)
        if result.get("status") != "success":
            logger.error("_send_follow_up | send failed flow=%d step=%d: %s", flow, template["step"], result)
            return False

    # Disparar automação (se houver)
    automation_key = template.get("automation")
    if automation_key:
        logger.info("_send_follow_up | triggering automation=%s", automation_key)
        await automation_client.trigger_automation(
            automation_key,
            conversation_id=conversation_id,
            contact_id=from_number,
            external_id=external_id,
        )

    # Atualizar estado na tabela dedicada follow_up_state (NÃO em session_data)
    step = template["step"]
    flag_key = _get_follow_flag_key(flow, step)
    now_iso = datetime.now(timezone.utc).isoformat()

    updates: dict[str, Any] = {flag_key: True}
    updates["follow_up_flow"] = flow
    updates["follow_up_flow_count"] = step

    # Only set started_at/anchor if not already set
    current = fus.get_state(session_id)
    if not current.get("follow_up_flow_started_at"):
        updates["follow_up_flow_started_at"] = now_iso
    if not current.get("follow_up_flow_anchor"):
        updates["follow_up_flow_anchor"] = now_iso

    # Sincronizar flags do agente para evitar reenvio
    if flow == 1 and step == 4:
        updates["automation_1_sent"] = True
    # FIX: sincronizar experiencia_sent quando scheduler manda flow 1 step 1
    if flow == 1 and step == 1:
        updates["experiencia_sent"] = True

    # Carregar templates para saber quantos o fluxo tem
    templates = _load_templates()
    flow_templates = templates.get(f"flow_{flow}", [])
    if step >= len(flow_templates):
        updates["follow_up_expired"] = True

    fus.update_many(session_id, updates)
    logger.info(
        "_send_follow_up | state updated: flow=%d step=%d flag=%s expired=%s",
        flow, step, flag_key, updates.get("follow_up_expired", False),
    )

    return True


async def _reset_follow_up(session_id: str) -> None:
    """Reset follow-up state when lead responds. Recalcula o fluxo."""
    try:
        # Read current state from follow_up_state table
        state = fus.get_state(session_id)

        # Also read from Agno session_data for automation flags that the agent sets
        agno_state = {}
        try:
            conn = sqlite3.connect(SESSION_DB_PATH)
            row = conn.execute(
                "SELECT session_data FROM agno_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            conn.close()
            if row:
                data = json.loads(row[0])
                while isinstance(data, str):
                    data = json.loads(data)
                if isinstance(data, dict):
                    agno_state = data.get("session_state", {})
        except Exception:
            pass

        # Sync automation flags from agent (in case agent set them)
        for key in ["automation_1_sent", "automation_2_sent", "experiencia_sent"]:
            if agno_state.get(key) and not state.get(key):
                state[key] = True

        # Sync follow_1_4_sent -> automation_1_sent
        if state.get("follow_1_4_sent") and not state.get("automation_1_sent"):
            state["automation_1_sent"] = True
        # FIX: sync follow_1_1_sent -> experiencia_sent
        if state.get("follow_1_1_sent") and not state.get("experiencia_sent"):
            state["experiencia_sent"] = True

        new_flow = _determine_flow(state)
        old_flow = state.get("follow_up_flow", 0)

        now_iso = datetime.now(timezone.utc).isoformat()

        updates = {
            "follow_up_flow": new_flow,
            "follow_up_flow_count": 0,
            "follow_up_flow_started_at": "",
            "follow_up_flow_anchor": "",
            "follow_up_expired": False,
            "last_lead_message_at": now_iso,
        }

        # Registrar primeiro contato (nunca sobrescrever)
        if not state.get("lead_first_contact_at"):
            updates["lead_first_contact_at"] = now_iso

        # Flags NÃO são resetadas — preservam o histórico de envios

        fus.update_many(session_id, updates)
        logger.info(
            "_reset_follow_up | session=%s flow: %d -> %d",
            session_id, old_flow, new_flow,
        )

    except Exception as exc:
        logger.error("_reset_follow_up | error: %s", exc)


async def _send_follow_janela_24h(
    session_id: str,
    state: dict,
    template: dict[str, Any],
    automation_client: DataCrazyAutomationClient,
) -> bool:
    """Send the janela 24h follow-up (1h before WhatsApp window closes)."""
    phone = _extract_phone(session_id)
    conversation_id = state.get("conversation_id", "")
    external_id = state.get("external_id", "")
    from_number = state.get("from_number", phone)

    if not conversation_id:
        logger.warning("_send_follow_janela_24h | no conversation_id for session=%s", session_id)
        return False

    # Enviar texto (se houver)
    message_text = template.get("message", "")
    if message_text:
        message = _format_message(message_text, state)
        logger.info("_send_follow_janela_24h | session=%s msg=%r", session_id, message[:80])
        result = await automation_client.send_text_message(conversation_id, message)
        if result.get("status") != "success":
            logger.error("_send_follow_janela_24h | send failed: %s", result)
            return False

    # Disparar automação (se houver)
    automation_key = template.get("automation")
    if automation_key:
        logger.info("_send_follow_janela_24h | triggering automation=%s", automation_key)
        await automation_client.trigger_automation(
            automation_key,
            conversation_id=conversation_id,
            contact_id=from_number,
            external_id=external_id,
        )

    # Atualizar estado na tabela dedicada (NÃO em session_data)
    fus.set_flag(session_id, "follow_janela_24h_sent", True)
    logger.info("_send_follow_janela_24h | state updated: follow_janela_24h_sent=True")

    return True


async def follow_up_scheduler_loop() -> None:
    """Main loop — runs as background task."""
    logger.info("follow_up_scheduler | starting (poll_interval=%ds)", _POLL_INTERVAL)
    automation = DataCrazyAutomationClient()

    # Ensure follow_up_state table exists
    fus.init_table()

    while True:
        try:
            # ── Business hours gate: skip follow-ups outside 08:00-23:00 Fortaleza ──
            within_hours = _is_within_business_hours()

            # ── Process pending responses when business hours start ──
            if within_hours:
                all_states = fus.get_all_states()
                for sid, st in all_states.items():
                    if st.get("pending_response"):
                        conv_id = st.get("conversation_id", "")
                        pending_text = st.get("pending_message_text", "")
                        if conv_id and pending_text:
                            logger.info(
                                "follow_up_scheduler | processing pending_response for %s conv=%s text=%r",
                                sid, conv_id, pending_text[:80],
                            )
                            try:
                                result = await automation.send_text_message(conv_id, pending_text)
                                if result.get("status") == "success":
                                    logger.info("follow_up_scheduler | pending message sent to %s", sid)
                                else:
                                    logger.error("follow_up_scheduler | pending send failed for %s: %s", sid, result)
                            except Exception as exc:
                                logger.error("follow_up_scheduler | pending send error for %s: %s", sid, exc)
                        else:
                            logger.warning(
                                "follow_up_scheduler | pending_response for %s but missing conv_id or text (conv=%r text=%r)",
                                sid, conv_id, pending_text[:50] if pending_text else "",
                            )
                        # Clear the flag regardless — don't retry forever
                        fus.update_many(sid, {
                            "pending_response": 0,
                            "pending_message_text": "",
                        })

            sessions = _get_active_sessions()
            logger.info("follow_up_scheduler | checking %d sessions", len(sessions))

            for session in sessions:
                session_id = session["session_id"]
                state = session["state"]
                now = datetime.now(timezone.utc)

                # Skip follow-ups outside business hours
                if not within_hours:
                    continue

                # Skip paused leads (tag agente_suporte_ia active)
                if state.get("paused"):
                    continue

                # --- Janela 24h: follow-up especial 1h antes de fechar ---
                first_contact = state.get("lead_first_contact_at", "")
                if (
                    first_contact
                    and not state.get("follow_janela_24h_sent", False)
                    and not state.get("is_purchased", False)
                ):
                    try:
                        first_dt = datetime.fromisoformat(first_contact)
                        if first_dt.tzinfo is None:
                            first_dt = first_dt.replace(tzinfo=timezone.utc)
                        elapsed_since_first = (now - first_dt).total_seconds()
                    except (ValueError, TypeError):
                        elapsed_since_first = 0

                    if 82800 <= elapsed_since_first <= 86400:
                        templates = _load_templates()
                        janela_tpl = templates.get("janela_24h")
                        if janela_tpl:
                            tpl = janela_tpl[0] if isinstance(janela_tpl, list) else janela_tpl
                            logger.info(
                                "follow_up_scheduler | janela_24h: session=%s elapsed=%.0fs",
                                session_id, elapsed_since_first,
                            )
                            await _send_follow_janela_24h(session_id, state, tpl, automation)
                        continue  # não processar fluxo normal neste ciclo

                # --- Fluxos normais ---
                result = _is_eligible(state)
                if result:
                    flow, template = result
                    logger.info(
                        "follow_up_scheduler | eligible: session=%s flow=%d step=%d",
                        session_id, flow, template["step"],
                    )
                    await _send_follow_up(session_id, state, flow, template, automation)

        except Exception as exc:
            logger.error("follow_up_scheduler | loop error: %s", exc, exc_info=True)

        await asyncio.sleep(_POLL_INTERVAL)
