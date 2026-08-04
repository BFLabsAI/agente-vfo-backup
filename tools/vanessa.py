from __future__ import annotations

import asyncio
import json
import logging
import time

from agno.tools import tool

from app.context import SessionContext
from app.datacrazy_automation import DataCrazyAutomationClient
from app import follow_up_state as fus

logger = logging.getLogger("vanessa.tools")

# ── Links base (sem tracking) — UTMs + src são adicionados em runtime ──
_APPLYFY_BASE = "https://checkout.applyfy.com.br/checkout/cmckomykl00sfad5yvjd30sfu?code=oi942sa"
_CAKTO_BASE = "https://pay.cakto.com.br"
_LINK_TIERS = {
    1: {"offer_id": "KRKF3CR", "value": 299.90},   # Padrão (full)
    2: {"offer_id": "V52KIF0", "value": 249.90},   # Negociação
    3: {"offer_id": "NNHY87K", "value": 199.90},   # Negociação
    4: {"offer_id": "QB8UZXN", "value": 179.90},   # Negociação
}
_DESAFIO_PRODUCT_ID = "m42xe54"
_DESAFIO_VALUE = 47.00
_CAMPAIGN_NAMES = {
    1: "full", 2: "tier_2", 3: "tier_3", 4: "tier_4",
}


def _build_tracking_link(offer_id: str, lead_id: str, campaign: str, is_cakto: bool = False) -> str:
    """Build a payment link with UTM tracking parameters."""
    if is_cakto:
        return f"{_CAKTO_BASE}/{offer_id}?utm_source=whatsappIA&utm_campaign={campaign}&src={lead_id}"
    return f"{_APPLYFY_BASE}&offer={offer_id}&utm_source=whatsappIA&utm_campaign={campaign}&src={lead_id}"


def _record_error(tool_name: str, exc: Exception, ctx: SessionContext, context: dict | None = None) -> None:
    try:
        import app.error_log as error_log
        error_log.record(
            session_id=f"vanessa-wa-{ctx.from_number}",
            from_number=ctx.from_number,
            tool_name=tool_name,
            exc=exc,
            context=context,
        )
    except Exception:
        pass


def build_vanessa_tools(ctx: SessionContext, automation: DataCrazyAutomationClient) -> list:

    @tool
    async def send_intro() -> str:
        """
        Send the introduction and ask for the lead's name.
        ALWAYS call this first when starting a conversation with a new lead.
        Sends two messages in exact order: 1. Introduction 2. Asks for name.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        if ctx.intro_sent:
            return json.dumps({"status": "skipped", "message": "Intro already sent. Do not call again."})
        try:
            await automation.send_text_message(conv_id, "Oie, sou a Vanessa, mas pode me chamar de Van!")
            await asyncio.sleep(1.5)
            await automation.send_text_message(conv_id, "E você, como se chama?")
            ctx.set_intro_sent(True)
            logger.info("send_intro | sent")
            return json.dumps({
                "status": "success",
                "message": "Intro sent. Wait for the lead to reply with their name.",
                "next_action": "When the lead replies with their name, call set_lead_info(name=...).",
            })
        except Exception as exc:
            _record_error("send_intro", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def send_text_message(text: str) -> str:
        """
        Send a text message to the lead via WhatsApp.
        Use this for ALL conversational messages.
        BLOCKED after first call per turn — second call returns skipped.

        Args:
            text: The message text to send to the lead.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})

        # ── DOUBLE-SEND GUARD: block second call in same turn ──
        call_count = ctx.add_text_msg_call()
        if ctx.text_msg_sent_this_turn:
            logger.warning(
                "send_text_message | BLOCKED — already sent this turn (call #%d). text=%r",
                call_count, text[:60],
            )
            return json.dumps({"status": "skipped", "message": "Already sent this turn"})

        try:
            result = await automation.send_text_message(conv_id, text)
            ctx.set_text_msg_sent_this_turn(True)
            logger.info("send_text_message | sent (call #%d): %s", call_count, text[:60])
            return json.dumps({"status": "success", "sent": text[:80]})
        except Exception as exc:
            _record_error("send_text_message", exc, ctx, {"text": text[:80]})
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def set_lead_info(name: str = "", profile: str = "", context: str = "") -> str:
        """
        Save lead information to the session context.
        Call this as soon as you learn the lead's name, profile, or situation.

        Args:
            name: The lead's first name.
            profile: Lead profile: 'iniciante', 'experiente_ruim', or 'experiente'.
            context: Brief summary of the lead's situation, pain point, or goal.
        """
        if name:
            ctx.set_lead_name(name.strip())
            # Persist lead_name to follow_up_state (survives Agno session overwrites)
            fus.set_value(f"vanessa-wa-{ctx.from_number}", "lead_name", name.strip())
            if ctx.funnel_phase == 0:
                ctx.set_funnel_phase(1)
        if profile:
            ctx.set_lead_profile(profile.strip())
        if context:
            ctx.set_lead_context(context.strip())

        return json.dumps({
            "status": "success",
            "saved": {
                "name": ctx.lead_name,
                "profile": ctx.lead_profile,
                "context": ctx.lead_context,
            },
        })

    @tool
    async def ask_motivation() -> str:
        """
        Ask the lead why they want to earn income from the internet.
        IMPORTANT: You MUST call trigger_mentoria() or trigger_comecando_do_zero() FIRST.
        This tool will NOT work if no audio tool was called before.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        if ctx.motivation_question_sent:
            return json.dumps({"status": "skipped", "message": "Motivation question already sent."})
        if not ctx.mentoria_sent and not ctx.comecando_do_zero_sent:
            # Also check follow_up_state (flag may have been set in the same batch)
            fus_mentoria = fus.get_flag(f"vanessa-wa-{ctx.from_number}", "mentoria_sent") if ctx.from_number else False
            fus_zero = fus.get_flag(f"vanessa-wa-{ctx.from_number}", "comecando_do_zero_sent") if ctx.from_number else False
            if not fus_mentoria and not fus_zero:
                return json.dumps({
                    "status": "error",
                    "message": "You MUST call trigger_mentoria() or trigger_comecando_do_zero() FIRST before asking motivation.",
                })
        # Cooldown: skip if a trigger tool sent a message in the same arun() cycle
        if (time.time() - ctx.last_tool_message_at) < 30:
            logger.info("ask_motivation | skipped — trigger cooldown active (< 30s)")
            return json.dumps({
                "status": "skipped",
                "message": "A trigger tool just sent a message. Wait for the lead to respond before asking motivation.",
                "next_action": "Wait for the lead's reply, then call ask_motivation() on the NEXT turn.",
            })
        try:
            name = ctx.lead_name or ""
            question = f"{name}, por qual motivo você quer iniciar a ter essa renda com a internet todos os meses? Só pra eu entender o seu momento atual e te orientar pro melhor caminho."
            await automation.send_text_message(conv_id, question)
            ctx.set_motivation_question_sent(True)
            ctx.set_last_tool_message_at(time.time())  # cooldown: block downstream tools
            logger.info("ask_motivation | sent")
            return json.dumps({
                "status": "success",
                "message": "Motivation question sent. Wait for the lead to reply.",
                "next_action": "When the lead replies, save their motivation with set_lead_info(context=...), then ask if you can send audios: '{name}, posso te mandar uns áudios e vídeos rápidos explicando como funciona?'",
            })
        except Exception as exc:
            _record_error("ask_motivation", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def trigger_experiencia() -> str:
        """
        Trigger automation that asks if the lead knows about affiliate market or mentorship.
        Call this AFTER saving the lead's name (Passo 1b).
        Replaces the old text-based qualification question.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        if ctx.experiencia_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "experiencia_sent") or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_1_sent"):
            return json.dumps({"status": "skipped", "message": "Experiencia automation already sent."})
        try:
            result = await automation.trigger_automation(
                "pergunta_experiencia", conv_id,
                contact_id=ctx.from_number,
                external_id=ctx.external_id,
            )
            if result.get("status") == "error":
                return json.dumps({
                    "status": "error",
                    "message": f"Experiencia automation failed: {result.get('message')}",
                })
            ctx.set_experiencia_sent(True)
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "experiencia_sent", True)
            # Agente já fez pergunta de qualificação — pular step 2 do follow-up
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_2_sent", True)
            await asyncio.sleep(10)
            logger.info("trigger_experiencia | success")
            return json.dumps({
                "status": "success",
                "message": "Experiencia automation triggered. Asks about affiliate market/mentorship experience.",
                "next_action": (
                    "Wait for the lead's response. "
                    "If they say they did mentorship/course → trigger_mentoria(). "
                    "If they say they don't know / never did → trigger_automation_1()."
                ),
            })
        except Exception as exc:
            _record_error("trigger_experiencia", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def trigger_mentoria() -> str:
        """
        Trigger automation for leads who already did mentorship/course.
        Call this when the lead mentions they already did a mentorship or course.
        After the audio finishes, call ask_motivation() to ask about their motivation.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        if ctx.mentoria_sent:
            return json.dumps({"status": "skipped", "message": "Mentoria automation already sent."})
        try:
            result = await automation.trigger_automation(
                "ja_fez_mentoria", conv_id,
                contact_id=ctx.from_number,
                external_id=ctx.external_id,
            )
            if result.get("status") == "error":
                return json.dumps({
                    "status": "error",
                    "message": f"Mentoria automation failed: {result.get('message')}",
                })
            ctx.set_mentoria_sent(True)
            # Agente já fez pergunta de qualificação — pular step 2 do follow-up
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_2_sent", True)
            await asyncio.sleep(10)
            logger.info("trigger_mentoria | success")
            # Auto-send motivation question after mentoria audio
            motivation_sent = False
            if not ctx.motivation_question_sent:
                motivation_sent = await _send_motivation_question()
            next_act = "Wait for the lead's response."
            if motivation_sent:
                next_act = "Motivation question sent after audio. Wait for the lead to reply with their motivation."
            return json.dumps({
                "status": "success",
                "message": "Mentoria automation triggered. Audio sent." + (" Motivation question also sent." if motivation_sent else ""),
                "next_action": next_act,
            })
        except Exception as exc:
            _record_error("trigger_mentoria", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def trigger_precisa_computador(cta: str = "") -> str:
        """Trigger audio: lead asks if they need a COMPUTER or CELLPHONE to work.
        ⚠️ NÃO use para perguntas sobre investimento em ferramentas ou anúncios — use trigger_preciso_pagar para isso."""
        return await _trigger_objection("precisa_computador", cta)

    @tool
    async def trigger_tempo_resultados(cta: str = "") -> str:
        """Trigger audio: lead asks how long to get results."""
        return await _trigger_objection("tempo_resultados", cta)

    @tool
    async def trigger_tempo_livre(cta: str = "") -> str:
        """Trigger audio: lead says they have little free time."""
        return await _trigger_objection("tempo_livre", cta)

    @tool
    async def trigger_experiencias_ruins(cta: str = "") -> str:
        """Trigger audio: lead had bad experiences with courses before."""
        return await _trigger_objection("experiencias_ruins", cta)

    @tool
    async def trigger_tem_medo(cta: str = "") -> str:
        """Trigger audio: lead says they are afraid or insecure."""
        return await _trigger_objection("tem_medo", cta)

    @tool
    async def trigger_tem_profissao(cta: str = "") -> str:
        """Trigger audio: lead mentions they already have a profession."""
        return await _trigger_objection("tem_profissao", cta)

    @tool
    async def trigger_outro_pais(cta: str = "") -> str:
        """Trigger audio: lead says they live outside Brazil."""
        return await _trigger_objection("outro_pais", cta)

    @tool
    async def trigger_e_mae(cta: str = "") -> str:
        """Trigger audio: lead says they are a mother."""
        return await _trigger_objection("e_mae", cta)

    @tool
    async def trigger_faz_faculdade(cta: str = "") -> str:
        """Trigger audio: lead says they are in college."""
        return await _trigger_objection("faz_faculdade", cta)

    @tool
    async def trigger_e_crista(cta: str = "") -> str:
        """Trigger audio: lead says they are Christian."""
        return await _trigger_objection("e_crista", cta)

    @tool
    async def trigger_como_sei_seguro(cta: str = "") -> str:
        """Trigger audio: lead asks if it's safe or trustworthy."""
        return await _trigger_objection("como_sei_seguro", cta)

    @tool
    async def trigger_comecando_do_zero() -> str:
        """Trigger audio: lead says they have no digital/internet experience.
        Automatically sends the motivation question after the audio."""
        result = await _trigger_objection("comecando_do_zero", "", auto_motivation=True)
        # Agente já fez pergunta de qualificação — pular step 2 do follow-up
        if ctx.comecando_do_zero_sent:
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_2_sent", True)
        return result

    @tool
    async def trigger_preciso_pagar(cta: str = "") -> str:
        """Trigger audio: lead asks if they need to INVEST MONEY in tools, ads, or products.
        Use when lead says 'investir', 'pagar para começar', 'gastar dinheiro', 'preciso de dinheiro'.
        ⚠️ NÃO use para perguntas sobre computador/celular — use trigger_precisa_computador para isso."""
        return await _trigger_objection("preciso_pagar", cta)

    @tool
    async def trigger_vai_ver() -> str:
        """Trigger audio: lead says they haven't seen the content yet but will see it."""
        return await _trigger_objection("vai_ver", "")

    async def _trigger_objection(key: str, cta: str, auto_motivation: bool = False) -> str:
        sent_flag = getattr(ctx, f"{key}_sent")
        if sent_flag:
            return json.dumps({"status": "skipped", "message": f"{key} automation already sent. Respond with text instead."})
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        try:
            result = await automation.trigger_automation(key, conv_id, contact_id=ctx.from_number, external_id=ctx.external_id)
            if result.get("status") == "error":
                return json.dumps({"status": "error", "message": f"{key} automation failed: {result.get('message')}"})
            getattr(ctx, f"set_{key}_sent")(True)
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", f"{key}_sent", True)
            ctx.set_last_tool_message_at(time.time())
            await asyncio.sleep(10)
            logger.info("trigger_%s | success", key)
            if cta:
                await automation.send_text_message(conv_id, cta)
                ctx.set_last_tool_message_at(time.time())
            # Auto-send motivation question after trigger (for comecando_do_zero / mentoria)
            motivation_sent = False
            if auto_motivation and not ctx.motivation_question_sent:
                motivation_sent = await _send_motivation_question()
            next_act = "Wait for the lead's response. Do NOT send another automation in the same turn."
            if motivation_sent:
                next_act = "Motivation question sent after audio. Wait for the lead to reply with their motivation."
            return json.dumps({"status": "success", "message": f"{key} automation triggered." + (" Motivation question also sent." if motivation_sent else ""), "next_action": next_act})
        except Exception as exc:
            _record_error(f"trigger_{key}", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    async def _send_motivation_question() -> bool:
        """Send motivation question to lead. Returns True if sent, False if skipped."""
        if ctx.motivation_question_sent:
            logger.info("_send_motivation_question | already sent, skipping")
            return False
        conv_id = ctx.conversation_id
        if not conv_id:
            return False
        try:
            name = ctx.lead_name or ""
            question = f"{name}, por qual motivo você quer iniciar a ter essa renda com a internet todos os meses? Só pra eu entender o seu momento atual e te orientar pro melhor caminho."
            await automation.send_text_message(conv_id, question)
            ctx.set_motivation_question_sent(True)
            ctx.set_last_tool_message_at(time.time())
            logger.info("_send_motivation_question | sent")
            return True
        except Exception as exc:
            _record_error("_send_motivation_question", exc, ctx)
            return False

    @tool
    async def trigger_automation_1() -> str:
        """
        Trigger automation 1 — presentation content (audios/videos).
        Call this AFTER saving lead profile and completing qualification questions in Passo 2.
        The automation ends by asking if the lead has any doubts.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        if ctx.automation_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_1_sent"):
            return json.dumps({"status": "skipped", "message": "Automation 1 already sent. Do NOT call this tool again. Continue the conversation naturally."})
        # Cooldown: bloquear se send_text_message foi chamado nos últimos 60s
        if (time.time() - ctx.last_tool_message_at) < 60:
            logger.info("trigger_automation_1 | blocked — text message sent recently (< 60s)")
            return json.dumps({
                "status": "blocked",
                "message": "You just sent a text message to the lead. WAIT for their response before triggering automation 1.",
            })
        try:
            result = await automation.trigger_automation(
                "automacao_1", conv_id,
                contact_id=ctx.from_number,
                external_id=ctx.external_id,
            )
            if result.get("status") == "error":
                return json.dumps({
                    "status": "error",
                    "message": f"Automation 1 failed: {result.get('message')}",
                })
            ctx.set_content_seen(True)
            ctx.set_automation_1_sent(True)
            ctx.set_follow_1_4_sent(True)  # impede scheduler de reenviar bf_labs_automacao1
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "automation_1_sent", True)
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_4_sent", True)
            ctx.set_funnel_phase(2)
            await asyncio.sleep(15)
            logger.info("trigger_automation_1 | success")
            return json.dumps({
                "status": "success",
                "message": "Automation 1 (presentation) triggered successfully.",
                "next_action": (
                    "Wait for the lead's response. "
                    "The automation ends by asking if they have doubts. "
                    "If they ask about price → FIRST ask if they can send a quick material showing what's included. "
                    "If they say yes → trigger_automation_2(). "
                    "If no doubts and ready to buy → present_price(tier=1). "
                    "If they say it's expensive → validate their pain, ask budget, then offer appropriate tier."
                ),
            })
        except Exception as exc:
            _record_error("trigger_automation_1", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def trigger_automation_2() -> str:
        """
        Trigger automation 2 — value-building before presenting price.
        The automation itself includes the price (R$299,90).
        Use ONLY the first time presenting price, after automation 1 was sent.
        Do NOT re-trigger during price negotiation/objections.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        # HARD GATE: automation_1 must be sent before automation_2
        a1_sent = ctx.automation_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_1_sent")
        if not a1_sent:
            return json.dumps({
                "status": "blocked",
                "message": "BLOCKED: automation_1 was NOT sent yet. You MUST send automation_1 FIRST and wait for the lead to confirm they saw the content before triggering automation_2. The lead must respond to 'ficou alguma dúvida?' first.",
            })
        if ctx.automation_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_2_sent"):
            return json.dumps({"status": "skipped", "message": "Automation 2 already sent. Do NOT call this tool again. If the lead accepted the price, call send_payment_link(tier=1). If they think it's expensive, use present_price(tier=2-4) for negotiation."})
        # Cooldown: bloquear se send_text_message foi chamado nos últimos 60s
        # força o LLM a esperar a resposta do lead antes de acionar automação 2
        if (time.time() - ctx.last_tool_message_at) < 60:
            logger.info("trigger_automation_2 | blocked — text message sent recently (< 60s)")
            return json.dumps({
                "status": "blocked",
                "message": "You just sent a text message to the lead. WAIT for their response before triggering automation 2. Do NOT call any tools until the lead replies.",
            })
        try:
            result = await automation.trigger_automation(
                "automacao_2", conv_id,
                contact_id=ctx.from_number,
                external_id=ctx.external_id,
            )
            if result.get("status") == "error":
                return json.dumps({
                    "status": "error",
                    "message": f"Automation 2 failed: {result.get('message')}",
                })
            ctx.set_automation_2_sent(True)
            fus.set_flag(f"vanessa-wa-{ctx.from_number}", "automation_2_sent", True)
            ctx.set_funnel_phase(3)
            await asyncio.sleep(15)
            logger.info("trigger_automation_2 | success")
            return json.dumps({
                "status": "success",
                "message": "Automation 2 (value-building/pricing) triggered successfully.",
                "next_action": (
                    "Automation 2 is now complete. "
                    "The automation already shows the price (R$299,90). "
                    "You MUST NOW immediately call send_payment_link(tier=1) in this same response. "
                    "Do NOT wait for the lead to respond. Do NOT send any other message. "
                    "Call send_payment_link(tier=1) RIGHT NOW to send the payment link. "
                    "Do NOT re-trigger automation 2 during price negotiation."
                ),
            })
        except Exception as exc:
            _record_error("trigger_automation_2", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def present_price(tier: int = 1) -> str:
        """
        Present the price to the lead and ask if it makes sense.
        Does NOT send the link. Use this FIRST when discussing price.
        After the lead responds positively, THEN call send_payment_link(tier).

        NOTE: Tier 1 (R$299,90) is already presented in automation 2.
        Use this tool ONLY for negotiation tiers 2-5 when the lead says the price is too high.

        Args:
            tier: 1 = R$299,90 (padrão, já enviado na automação 2), 2 = R$249,90, 3 = R$199,90, 4 = R$179,90.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})

        if tier == 1:
            return json.dumps({
                "status": "blocked",
                "message": (
                    "TIER 1 (R$299,90) is already presented in automation 2. "
                    "Do NOT call present_price(tier=1). "
                    "If the lead accepts tier 1, call send_payment_link(tier=1) directly. "
                    "If the lead says it's expensive, call present_price(tier=2) or lower."
                ),
            })

        if not ctx.automation_2_sent:
            return json.dumps({
                "status": "blocked",
                "message": (
                    "PRICE BLOCKED: automation_2_sent is False. "
                    "You MUST call trigger_automation_2() FIRST and wait for it to complete. "
                    "Only after automation_2_sent becomes True can you call present_price(). "
                    "Call get_lead_info() to check current state."
                ),
            })

        name = ctx.lead_name
        offers = {
            2: {
                "price": "R$249,90",
                "description": "condição especial para garantir hoje",
            },
            3: {
                "price": "R$199,90",
                "description": "oferta única para quem quer começar agora",
            },
            4: {
                "price": "R$179,90",
                "description": "última oferta especial",
            },
        }

        offer = offers.get(tier)
        if not offer:
            return json.dumps({"status": "error", "message": f"Invalid tier {tier}. Use 2, 3, or 4."})

        try:
            if tier == 2:
                body = (
                    f"{name}, super te entendo. "
                    f"Consigo liberar pra você por {offer['price']}. "
                    f"O que acha?"
                )
            elif tier == 3:
                body = (
                    f"{name}, consegui uma condição ainda melhor: {offer['price']}. "
                    f"É {offer['description']}. Bora?"
                )
            elif tier == 4:
                body = (
                    f"{name}, olha o que consegui aqui: {offer['price']}. "
                    f"É {offer['description']}. Vamos?"
                )
            else:
                body = (
                    f"{name}, minha última oferta é {offer['price']}. "
                    f"É {offer['description']}. Não faço isso pra qualquer um kkkkk. Bora?"
                )

            await automation.send_text_message(conv_id, body)
            ctx.set_funnel_phase(4)
            logger.info("present_price | tier=%d sent", tier)
            return json.dumps({
                "status": "success",
                "tier": tier,
                "price": offer["price"],
                "next_action": (
                    "Wait for the lead's response. "
                    "If they say yes / it makes sense → call send_payment_link(tier) to send the link. "
                    "If they say it's expensive → validate their pain, ask 'quanto teria disponível pra investir?' "
                    "Then offer the closest tier based on their budget. "
                    "If they can't afford any tier → offer the 7-day challenge with send_challenge_link(). "
                    "IMPORTANT: Wait for response between tiers. Never send two tiers in the same turn."
                ),
            })
        except Exception as exc:
            _record_error("present_price", exc, ctx, {"tier": tier})
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def send_payment_link(tier: int = 1) -> str:
        """
        Send the payment link to the lead.
        Sends the full payment template with link, payment methods, and bonuses.
        Do NOT send any additional messages with send_text_message() when using this tool.

        ⚠️ CRITICAL RULES:
        - Call this DIRECTLY when the lead accepts — do NOT send a text confirmation first.
        - ONLY call this when the lead EXPLICITLY accepts the price and asks for the link.
        - NEVER call this automatically after automation_2. AGUARDE the lead to accept first.
        - Valid acceptance signals: 'quero', 'aceito', 'manda o link', 'pode mandar', 'vamos', 'bora', 'faz sim', 'faz sentido'
        - INVALID signals (do NOT send link): 'quanto?', 'como funciona?', 'me conta mais', 'deixa eu pensar'

        Args:
            tier: 1 = R$299,90 (padrão), 2 = R$249,90, 3 = R$199,90, 4 = R$179,90.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})

        # ── HARD GATE: automações 1 e 2 devem ter sido enviadas ──
        a1_sent = ctx.automation_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_1_sent")
        a2_sent = ctx.automation_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_2_sent")
        if not a1_sent or not a2_sent:
            missing = []
            if not a1_sent:
                missing.append("automation_1")
            if not a2_sent:
                missing.append("automation_2")
            return json.dumps({
                "status": "blocked",
                "message": f"BLOCKED: {', '.join(missing)} not sent yet. You MUST complete the full funnel (automation 1 + automation 2) BEFORE sending the payment link. The lead must see the content and accept the price first.",
            })

        # Bloquear se follow-up do fluxo 3 já enviou link de promoção
        # Checa AMBAS as fontes: ctx (Agno) e follow_up_state (scheduler)
        flow3_sent = ctx.follow_janela_24h_sent
        if not flow3_sent:
            # Fallback: checar na tabela follow_up_state (scheduler pode ter setado sem o Agno ver)
            try:
                flow3_sent = fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_janela_24h_sent")
            except Exception:
                pass

        if flow3_sent:
            return json.dumps({
                "status": "blocked",
                "message": "The lead already received a promotional link via follow-up. Do NOT send payment link again. If the lead wants to buy, guide them to use the link they already received. If they have price objections, use present_price(tier=2-5).",
            })

        tier_info = _LINK_TIERS.get(tier)
        if not tier_info:
            return json.dumps({"status": "error", "message": f"Invalid tier: {tier}. Valid: 1-5."})

        lead_id = ctx.external_id or ""
        campaign = _CAMPAIGN_NAMES.get(tier, f"tier_{tier}")
        link = _build_tracking_link(tier_info["offer_id"], lead_id, campaign)

        try:
            payment_msg = (
                f"LINK DE PAGAMENTO:\n{link}\n\n"
                f"(Caso deseje mudar a quantidade de parcelas, clique em \"Editar parcelas\")\n\n"
                f"Formas de Pagamento:\n"
                f"• Cartão de crédito em até 12x, PIX ou boleto bancário à vista!\n"
                f"• Dá para pagar usando mais de um cartão (caso você não tenha o limite todo em um cartão)\n"
                f"• Não dá para pagar com cartão de débito. Se você só tiver a opção de débito, deve gerar o código PIX, copiar o código copia e cola e pagar pelo app do banco.\n\n"
                f"✅+ SUPORTE GRATUITO\n"
                f"✅+ DESCONTO EXCLUSIVO\n"
                f"✅+ 4 MÓDULOS BÔNUS"
            )
            await automation.send_text_message(conv_id, payment_msg)
            ctx.set_is_interested(True)
            ctx.set_is_purchased(True)
            ctx.set_payment_tier_sent(tier)
            ctx.set_funnel_phase(6)

            # Trigger pós-pagamento automation (upsells, acesso vitalício, etc.)
            try:
                await automation.trigger_automation(
                    "pos_pagamento",
                    conversation_id=conv_id,
                    contact_id=ctx.from_number,
                    external_id=ctx.external_id or "",
                )
                logger.info("send_payment_link | pos_pagamento automation triggered")
            except Exception as auto_exc:
                logger.warning("send_payment_link | pos_pagamento trigger failed (non-blocking): %s", auto_exc)

            # Register in payment_links
            fus.record_link_sent(
                lead_id=lead_id,
                phone=ctx.from_number,
                session_id=f"vanessa-wa-{ctx.from_number}",
                link_url=link,
                utm_campaign=campaign,
            )
            logger.info("send_payment_link | tier=%d sent link=%s", tier, link)
            return json.dumps({
                "status": "success",
                "tier": tier,
                "link": link,
                "next_action": (
                    "Wait for the lead's response. "
                    "If they confirm payment → celebrate and guide them. "
                    "If they have questions → answer patiently."
                ),
            })
        except Exception as exc:
            _record_error("send_payment_link", exc, ctx, {"tier": tier})
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def send_challenge_link() -> str:
        """
        Send the 7-Day Challenge link (R$47) via Cakto.
        Call this when the lead ACCEPTS the challenge offer.
        Sends the full payment template with link, payment methods, and bonuses.
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        try:
            lead_id = ctx.external_id or ""
            link = _build_tracking_link(_DESAFIO_PRODUCT_ID, lead_id, "desafio", is_cakto=True)

            payment_msg = (
                f"LINK DE PAGAMENTO:\n{link}\n\n"
                f"(Caso deseje mudar a quantidade de parcelas, clique em \"Editar parcelas\")\n\n"
                f"Formas de Pagamento:\n"
                f"• Cartão de crédito em até 12x, PIX ou boleto bancário à vista!\n"
                f"• Dá para pagar usando mais de um cartão (caso você não tenha o limite todo em um cartão)\n"
                f"• Não dá para pagar com cartão de débito. Se você só tiver a opção de débito, deve gerar o código PIX, copiar o código copia e cola e pagar pelo app do banco.\n\n"
                f"✅+ SUPORTE GRATUITO\n"
                f"✅+ DESCONTO EXCLUSIVO\n"
                f"✅+ 4 MÓDULOS BÔNUS"
            )
            await automation.send_text_message(conv_id, payment_msg)
            ctx.set_challenge_offered(True)
            ctx.set_funnel_phase(6)

            # Trigger pós-pagamento automation (upsells, acesso vitalício, etc.)
            try:
                await automation.trigger_automation(
                    "pos_pagamento",
                    conversation_id=conv_id,
                    contact_id=ctx.from_number,
                    external_id=ctx.external_id or "",
                )
                logger.info("send_challenge_link | pos_pagamento automation triggered")
            except Exception as auto_exc:
                logger.warning("send_challenge_link | pos_pagamento trigger failed (non-blocking): %s", auto_exc)

            # Register in payment_links
            fus.record_link_sent(
                lead_id=lead_id,
                phone=ctx.from_number,
                session_id=f"vanessa-wa-{ctx.from_number}",
                link_url=link,
                utm_campaign="desafio",
            )
            logger.info("send_challenge_link | sent link=%s", link)
            return json.dumps({
                "status": "success",
                "message": "7-Day Challenge link (R$47) sent.",
                "next_action": (
                    "Wait for the lead's response. "
                    "If they confirm payment → celebrate and guide them. "
                    "If they have questions → answer patiently."
                ),
            })
        except Exception as exc:
            _record_error("send_challenge_link", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def send_cakto_link() -> str:
        """
        Send the Cakto link for the second product (member area + challenge).
        Call this ONLY when the lead explicitly says they already bought the first product (Your Boss).
        Link: https://pay.cakto.com.br/39ogt3h
        """
        conv_id = ctx.conversation_id
        if not conv_id:
            return json.dumps({"status": "error", "message": "No conversation_id available."})
        try:
            body = (
                "Que bom que você já faz parte do Your Boss! "
                "Então esse link aqui é pra você acessar a área de membros e o desafio: "
                "https://pay.cakto.com.br/39ogt3h\n\n"
                "Qualquer dúvida, estou por aqui!"
            )
            await automation.send_text_message(conv_id, body)
            ctx.set_is_purchased(True)
            logger.info("send_cakto_link | sent")
            return json.dumps({
                "status": "success",
                "message": "Cakto link (second product) sent.",
                "next_action": (
                    "Wait for the lead's response. Answer any questions with send_text_message()."
                ),
            })
        except Exception as exc:
            _record_error("send_cakto_link", exc, ctx)
            return json.dumps({"status": "error", "message": str(exc)})

    @tool
    async def get_lead_info() -> str:
        """
        Get current lead information and session state.
        Use this to check what has been sent already.
        """
        return json.dumps({
            "status": "success",
            "lead": {
                "name": ctx.lead_name,
                "profile": ctx.lead_profile,
                "context": ctx.lead_context,
            },
            "commercial": {
                "interested": ctx.is_interested,
                "purchased": ctx.is_purchased,
            },
            "automation": {
                "automation_1_sent": ctx.automation_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_1_sent"),
                "automation_2_sent": ctx.automation_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "automation_2_sent"),
                "experiencia_sent": ctx.experiencia_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "experiencia_sent"),
                "mentoria_sent": ctx.mentoria_sent,
                "motivation_question_sent": ctx.motivation_question_sent,
                "content_seen": ctx.content_seen,
            },
            "objections": {
                "precisa_computador_sent": ctx.precisa_computador_sent,
                "tempo_resultados_sent": ctx.tempo_resultados_sent,
                "tempo_livre_sent": ctx.tempo_livre_sent,
                "experiencias_ruins_sent": ctx.experiencias_ruins_sent,
                "tem_medo_sent": ctx.tem_medo_sent,
                "tem_profissao_sent": ctx.tem_profissao_sent,
                "outro_pais_sent": ctx.outro_pais_sent,
                "e_mae_sent": ctx.e_mae_sent,
                "faz_faculdade_sent": ctx.faz_faculdade_sent,
                "e_crista_sent": ctx.e_crista_sent,
                "como_sei_seguro_sent": ctx.como_sei_seguro_sent,
                "comecando_do_zero_sent": ctx.comecando_do_zero_sent,
                "preciso_pagar_sent": ctx.preciso_pagar_sent,
            },
            "funnel": {
                "phase": ctx.funnel_phase,
                "qualified": ctx.is_qualified,
                "budget": ctx.lead_budget,
                "challenge_offered": ctx.challenge_offered,
            },
            "follow_up_status": {
                "current_flow": fus.get_int(f"vanessa-wa-{ctx.from_number}", "follow_up_flow") or ctx.follow_up_flow,
                "flow_count": fus.get_int(f"vanessa-wa-{ctx.from_number}", "follow_up_flow_count") or ctx.follow_up_flow_count,
                "expired": fus.get_bool(f"vanessa-wa-{ctx.from_number}", "follow_up_expired") or ctx.follow_up_expired,
                "flow_1": {
                    "follow_1_1": ctx.follow_1_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_1_sent"),
                    "follow_1_2": ctx.follow_1_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_2_sent"),
                    "follow_1_3": ctx.follow_1_3_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_3_sent"),
                    "follow_1_4": ctx.follow_1_4_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_1_4_sent"),
                },
                "flow_2": {
                    "follow_2_1": ctx.follow_2_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_2_1_sent"),
                    "follow_2_2": ctx.follow_2_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_2_2_sent"),
                    "follow_2_3": ctx.follow_2_3_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_2_3_sent"),
                },
                "flow_3": {
                    "follow_3_1": ctx.follow_3_1_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_3_1_sent"),
                    "follow_3_2": ctx.follow_3_2_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_3_2_sent"),
                    "follow_3_3": ctx.follow_3_3_sent or fus.get_flag(f"vanessa-wa-{ctx.from_number}", "follow_3_3_sent"),
                },
            },
        })

    @tool
    async def pause_lead(reason: str = "") -> str:
        """
        Pause all follow-up messages for this lead.
        Call this when the lead explicitly says they don't want more messages,
        have no interest, or ask to stop receiving messages.

        Valid triggers:
        - "não quero mais"
        - "para de mandar mensagem"
        - "não tenho interesse"
        - "me tira da lista"
        - "não me manda mais nada"
        - "quero parar de receber"

        The lead will be auto-resumed if they send a new message later.

        Args:
            reason: Brief reason for pausing (for logging).
        """
        session_id = f"vanessa-wa-{ctx.from_number}"
        fus.set_flag(session_id, "paused", True)
        logger.info("pause_lead | session=%s reason=%r", session_id, reason)
        return json.dumps({
            "status": "paused",
            "message": "Follow-up paused for this lead. They will not receive any more automated messages. If the lead sends a new message, they will be auto-resumed.",
        })

    return [
        send_intro,
        send_text_message,
        set_lead_info,
        ask_motivation,
        trigger_experiencia,
        trigger_mentoria,
        trigger_precisa_computador,
        trigger_tempo_resultados,
        trigger_tempo_livre,
        trigger_experiencias_ruins,
        trigger_tem_medo,
        trigger_tem_profissao,
        trigger_outro_pais,
        trigger_e_mae,
        trigger_faz_faculdade,
        trigger_e_crista,
        trigger_como_sei_seguro,
        trigger_comecando_do_zero,
        trigger_preciso_pagar,
        trigger_vai_ver,
        present_price,
        trigger_automation_1,
        trigger_automation_2,
        send_payment_link,
        send_challenge_link,
        send_cakto_link,
        get_lead_info,
        pause_lead,
    ]
