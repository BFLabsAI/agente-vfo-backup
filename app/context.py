from __future__ import annotations

from typing import Any

from app import follow_up_state as fus


class SessionContext:
    """
    Typed wrapper over Agno's agent.session_state dict.
    Tools read/write state here — Agno persists it to SQLite automatically.
    """

    def __init__(self, state: dict[str, Any]) -> None:
        self._s = state

    # --- Identifiers ---
    @property
    def from_number(self) -> str:
        return self._s.get("from_number", "")

    @property
    def _session_id(self) -> str:
        """Derive session_id for follow_up_state lookups."""
        fn = self.from_number
        return f"vanessa-wa-{fn}" if fn else ""

    # --- Lead identity ---
    @property
    def lead_name(self) -> str:
        return self._s.get("lead_name", "")

    def set_lead_name(self, v: str) -> None:
        self._s["lead_name"] = v

    @property
    def lead_profile(self) -> str:
        return self._s.get("lead_profile", "")

    def set_lead_profile(self, v: str) -> None:
        self._s["lead_profile"] = v

    @property
    def lead_context(self) -> str:
        return self._s.get("lead_context", "")

    def set_lead_context(self, v: str) -> None:
        self._s["lead_context"] = v

    # --- Commercial state ---
    @property
    def is_interested(self) -> bool:
        return self._s.get("is_interested", False)

    def set_is_interested(self, v: bool) -> None:
        self._s["is_interested"] = v

    @property
    def is_purchased(self) -> bool:
        return self._s.get("is_purchased", False)

    def set_is_purchased(self, v: bool) -> None:
        self._s["is_purchased"] = v
        if self._session_id:
            fus.set_flag(self._session_id, "is_purchased", v)

    @property
    def payment_tier_sent(self) -> int:
        return self._s.get("payment_tier_sent", 0)

    def set_payment_tier_sent(self, v: int) -> None:
        self._s["payment_tier_sent"] = v
        if self._session_id:
            fus.set_value(self._session_id, "payment_tier_sent", v)

    # --- Operational ---
    @property
    def conversation_id(self) -> str | None:
        return self._s.get("conversation_id")

    def set_conversation_id(self, v: str) -> None:
        self._s["conversation_id"] = v

    @property
    def external_id(self) -> str:
        return self._s.get("external_id", "")

    def set_external_id(self, v: str) -> None:
        self._s["external_id"] = v

    # --- Media context ---
    @property
    def last_media_type(self) -> str:
        return self._s.get("last_media_type", "")

    def set_last_media_type(self, v: str) -> None:
        self._s["last_media_type"] = v

    @property
    def last_media_url(self) -> str:
        return self._s.get("last_media_url", "")

    def set_last_media_url(self, v: str) -> None:
        self._s["last_media_url"] = v

    @property
    def last_media_content_type(self) -> str:
        return self._s.get("last_media_content_type", "")

    def set_last_media_content_type(self, v: str) -> None:
        self._s["last_media_content_type"] = v

    @property
    def last_media_summary(self) -> str:
        return self._s.get("last_media_summary", "")

    def set_last_media_summary(self, v: str) -> None:
        self._s["last_media_summary"] = v

    @property
    def last_media_synthetic_text(self) -> str:
        return self._s.get("last_media_synthetic_text", "")

    def set_last_media_synthetic_text(self, v: str) -> None:
        self._s["last_media_synthetic_text"] = v

    @property
    def last_media_received_at(self) -> str:
        return self._s.get("last_media_received_at", "")

    def set_last_media_received_at(self, v: str) -> None:
        self._s["last_media_received_at"] = v

    # --- Qualification & Engagement ---
    @property
    def engagement_score(self) -> int:
        return self._s.get("engagement_score", 0)

    def set_engagement_score(self, v: int) -> None:
        self._s["engagement_score"] = v

    def add_engagement_points(self, points: int) -> None:
        self._s["engagement_score"] = min(self._s.get("engagement_score", 0) + points, 10)

    @property
    def content_seen(self) -> bool:
        return self._s.get("content_seen", False)

    def set_content_seen(self, v: bool) -> None:
        self._s["content_seen"] = v

    # --- Negotiation ---
    @property
    def lead_budget(self) -> float:
        return self._s.get("lead_budget", 0.0)

    def set_lead_budget(self, v: float) -> None:
        self._s["lead_budget"] = v

    @property
    def negotiated_amount(self) -> float:
        return self._s.get("negotiated_amount", 0.0)

    def set_negotiated_amount(self, v: float) -> None:
        self._s["negotiated_amount"] = v

    @property
    def challenge_offered(self) -> bool:
        return self._s.get("challenge_offered", False)

    def set_challenge_offered(self, v: bool) -> None:
        self._s["challenge_offered"] = v

    # --- Qualification ---
    @property
    def is_qualified(self) -> bool:
        return self._s.get("is_qualified", False)

    def set_is_qualified(self, v: bool) -> None:
        self._s["is_qualified"] = v

    # --- Intro tracking ---
    @property
    def intro_sent(self) -> bool:
        return self._s.get("intro_sent", False)

    def set_intro_sent(self, v: bool) -> None:
        self._s["intro_sent"] = v

    # --- Automation tracking ---
    @property
    def automation_1_sent(self) -> bool:
        if self._session_id and fus.get_flag(self._session_id, "automation_1_sent"):
            return True
        return self._s.get("automation_1_sent", False)

    def set_automation_1_sent(self, v: bool) -> None:
        self._s["automation_1_sent"] = v
        if self._session_id:
            fus.set_flag(self._session_id, "automation_1_sent", v)

    @property
    def automation_2_sent(self) -> bool:
        if self._session_id and fus.get_flag(self._session_id, "automation_2_sent"):
            return True
        return self._s.get("automation_2_sent", False)

    def set_automation_2_sent(self, v: bool) -> None:
        self._s["automation_2_sent"] = v
        if self._session_id:
            fus.set_flag(self._session_id, "automation_2_sent", v)

    @property
    def experiencia_sent(self) -> bool:
        if self._session_id and fus.get_flag(self._session_id, "experiencia_sent"):
            return True
        return self._s.get("experiencia_sent", False)

    def set_experiencia_sent(self, v: bool) -> None:
        self._s["experiencia_sent"] = v
        if self._session_id:
            fus.set_flag(self._session_id, "experiencia_sent", v)

    @property
    def mentoria_sent(self) -> bool:
        return self._s.get("mentoria_sent", False)

    def set_mentoria_sent(self, v: bool) -> None:
        self._s["mentoria_sent"] = v

    # --- Motivation question tracking ---
    @property
    def motivation_question_sent(self) -> bool:
        return self._s.get("motivation_question_sent", False)

    def set_motivation_question_sent(self, v: bool) -> None:
        self._s["motivation_question_sent"] = v

    # --- Objection handling automations ---
    @property
    def precisa_computador_sent(self) -> bool:
        return self._s.get("precisa_computador_sent", False)

    def set_precisa_computador_sent(self, v: bool) -> None:
        self._s["precisa_computador_sent"] = v

    @property
    def tempo_resultados_sent(self) -> bool:
        return self._s.get("tempo_resultados_sent", False)

    def set_tempo_resultados_sent(self, v: bool) -> None:
        self._s["tempo_resultados_sent"] = v

    @property
    def tempo_livre_sent(self) -> bool:
        return self._s.get("tempo_livre_sent", False)

    def set_tempo_livre_sent(self, v: bool) -> None:
        self._s["tempo_livre_sent"] = v

    @property
    def experiencias_ruins_sent(self) -> bool:
        return self._s.get("experiencias_ruins_sent", False)

    def set_experiencias_ruins_sent(self, v: bool) -> None:
        self._s["experiencias_ruins_sent"] = v

    @property
    def tem_medo_sent(self) -> bool:
        return self._s.get("tem_medo_sent", False)

    def set_tem_medo_sent(self, v: bool) -> None:
        self._s["tem_medo_sent"] = v

    @property
    def tem_profissao_sent(self) -> bool:
        return self._s.get("tem_profissao_sent", False)

    def set_tem_profissao_sent(self, v: bool) -> None:
        self._s["tem_profissao_sent"] = v

    @property
    def outro_pais_sent(self) -> bool:
        return self._s.get("outro_pais_sent", False)

    def set_outro_pais_sent(self, v: bool) -> None:
        self._s["outro_pais_sent"] = v

    @property
    def e_mae_sent(self) -> bool:
        return self._s.get("e_mae_sent", False)

    def set_e_mae_sent(self, v: bool) -> None:
        self._s["e_mae_sent"] = v

    @property
    def faz_faculdade_sent(self) -> bool:
        return self._s.get("faz_faculdade_sent", False)

    def set_faz_faculdade_sent(self, v: bool) -> None:
        self._s["faz_faculdade_sent"] = v

    @property
    def e_crista_sent(self) -> bool:
        return self._s.get("e_crista_sent", False)

    def set_e_crista_sent(self, v: bool) -> None:
        self._s["e_crista_sent"] = v

    @property
    def como_sei_seguro_sent(self) -> bool:
        return self._s.get("como_sei_seguro_sent", False)

    def set_como_sei_seguro_sent(self, v: bool) -> None:
        self._s["como_sei_seguro_sent"] = v

    @property
    def comecando_do_zero_sent(self) -> bool:
        return self._s.get("comecando_do_zero_sent", False)

    def set_comecando_do_zero_sent(self, v: bool) -> None:
        self._s["comecando_do_zero_sent"] = v

    @property
    def preciso_pagar_sent(self) -> bool:
        return self._s.get("preciso_pagar_sent", False)

    def set_preciso_pagar_sent(self, v: bool) -> None:
        self._s["preciso_pagar_sent"] = v

    @property
    def vai_ver_sent(self) -> bool:
        return self._s.get("vai_ver_sent", False)

    def set_vai_ver_sent(self, v: bool) -> None:
        self._s["vai_ver_sent"] = v

    # --- Funnel phase ---
    @property
    def funnel_phase(self) -> int:
        return self._s.get("funnel_phase", 0)

    def set_funnel_phase(self, v: int) -> None:
        self._s["funnel_phase"] = v

    # --- Anti-repetition ---
    @property
    def last_question_asked(self) -> str:
        return self._s.get("last_question_asked", "")

    def set_last_question_asked(self, v: str) -> None:
        self._s["last_question_asked"] = v

    # --- Tool message cooldown (prevents duplicate sends in same arun) ---
    @property
    def last_tool_message_at(self) -> float:
        """Timestamp (time.time()) of last message sent by a tool. Used to prevent
        ask_motivation from firing in the same arun() as a trigger tool."""
        return self._s.get("_last_tool_message_at", 0.0)

    def set_last_tool_message_at(self, v: float) -> None:
        self._s["_last_tool_message_at"] = v

    # --- Double-send guard ---
    @property
    def text_msg_sent_this_turn(self) -> bool:
        """True if send_text_message was already called this turn. Resets each turn."""
        return self._s.get("_text_msg_sent_this_turn", False)

    def set_text_msg_sent_this_turn(self, v: bool) -> None:
        self._s["_text_msg_sent_this_turn"] = v

    @property
    def text_msg_call_count(self) -> int:
        """How many times send_text_message was called this turn (for monitoring)."""
        return self._s.get("_text_msg_call_count", 0)

    def add_text_msg_call(self) -> int:
        """Increment and return the call count."""
        count = self._s.get("_text_msg_call_count", 0) + 1
        self._s["_text_msg_call_count"] = count
        return count

    # --- Follow-up tracking (v2 - multi-flow) ---
    @property
    def last_lead_message_at(self) -> str:
        return self._s.get("last_lead_message_at", "")

    def set_last_lead_message_at(self, v: str) -> None:
        self._s["last_lead_message_at"] = v

    @property
    def follow_up_flow(self) -> int:
        fus_val = fus.get_int(self._session_id, "follow_up_flow") if self._session_id else 0
        return fus_val or self._s.get("follow_up_flow", 0)

    def set_follow_up_flow(self, v: int) -> None:
        self._s["follow_up_flow"] = v
        if self._session_id:
            fus.set_value(self._session_id, "follow_up_flow", v)

    @property
    def follow_up_flow_count(self) -> int:
        fus_val = fus.get_int(self._session_id, "follow_up_flow_count") if self._session_id else 0
        return fus_val or self._s.get("follow_up_flow_count", 0)

    def set_follow_up_flow_count(self, v: int) -> None:
        self._s["follow_up_flow_count"] = v
        if self._session_id:
            fus.set_value(self._session_id, "follow_up_flow_count", v)

    def increment_follow_up_flow_count(self) -> None:
        self._s["follow_up_flow_count"] = self._s.get("follow_up_flow_count", 0) + 1

    @property
    def follow_up_flow_started_at(self) -> str:
        fus_val = fus.get_str(self._session_id, "follow_up_flow_started_at") if self._session_id else ""
        return fus_val or self._s.get("follow_up_flow_started_at", "")

    def set_follow_up_flow_started_at(self, v: str) -> None:
        self._s["follow_up_flow_started_at"] = v
        if self._session_id:
            fus.set_value(self._session_id, "follow_up_flow_started_at", v)

    @property
    def follow_up_expired(self) -> bool:
        fus_val = fus.get_bool(self._session_id, "follow_up_expired") if self._session_id else False
        return fus_val or self._s.get("follow_up_expired", False)

    def set_follow_up_expired(self, v: bool) -> None:
        self._s["follow_up_expired"] = v
        if self._session_id:
            fus.set_flag(self._session_id, "follow_up_expired", v)

    # --- Flags por follow-up enviado (anti-duplicação) ---
    # Fluxo 1
    @property
    def follow_1_1_sent(self) -> bool:
        return self._s.get("follow_1_1_sent", False)

    def set_follow_1_1_sent(self, v: bool) -> None:
        self._s["follow_1_1_sent"] = v

    @property
    def follow_1_2_sent(self) -> bool:
        return self._s.get("follow_1_2_sent", False)

    def set_follow_1_2_sent(self, v: bool) -> None:
        self._s["follow_1_2_sent"] = v

    @property
    def follow_1_3_sent(self) -> bool:
        return self._s.get("follow_1_3_sent", False)

    def set_follow_1_3_sent(self, v: bool) -> None:
        self._s["follow_1_3_sent"] = v

    @property
    def follow_1_4_sent(self) -> bool:
        return self._s.get("follow_1_4_sent", False)

    def set_follow_1_4_sent(self, v: bool) -> None:
        self._s["follow_1_4_sent"] = v

    # Fluxo 2
    @property
    def follow_2_1_sent(self) -> bool:
        return self._s.get("follow_2_1_sent", False)

    def set_follow_2_1_sent(self, v: bool) -> None:
        self._s["follow_2_1_sent"] = v

    @property
    def follow_2_2_sent(self) -> bool:
        return self._s.get("follow_2_2_sent", False)

    def set_follow_2_2_sent(self, v: bool) -> None:
        self._s["follow_2_2_sent"] = v

    @property
    def follow_2_3_sent(self) -> bool:
        return self._s.get("follow_2_3_sent", False)

    def set_follow_2_3_sent(self, v: bool) -> None:
        self._s["follow_2_3_sent"] = v

    # Fluxo 3
    @property
    def follow_3_1_sent(self) -> bool:
        return self._s.get("follow_3_1_sent", False)

    def set_follow_3_1_sent(self, v: bool) -> None:
        self._s["follow_3_1_sent"] = v

    @property
    def follow_3_2_sent(self) -> bool:
        return self._s.get("follow_3_2_sent", False)

    def set_follow_3_2_sent(self, v: bool) -> None:
        self._s["follow_3_2_sent"] = v

    @property
    def follow_3_3_sent(self) -> bool:
        return self._s.get("follow_3_3_sent", False)

    def set_follow_3_3_sent(self, v: bool) -> None:
        self._s["follow_3_3_sent"] = v

    @property
    def follow_janela_24h_sent(self) -> bool:
        return self._s.get("follow_janela_24h_sent", False)

    def set_follow_janela_24h_sent(self, v: bool) -> None:
        self._s["follow_janela_24h_sent"] = v
