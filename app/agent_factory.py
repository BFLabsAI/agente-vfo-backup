from __future__ import annotations

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb

from app.config import SESSION_DB_PATH
from app.context import SessionContext
from app.datacrazy_automation import DataCrazyAutomationClient
from app.llm_factory import build_model
from prompts.vanessa import build_system_prompt
from tools.vanessa import build_vanessa_tools


def create_vanessa_agent(
    session_id: str = "vanessa-default",
    from_number: str = "",
    conversation_id: str = "",
) -> Agent:
    state: dict = {
        "from_number": from_number,
        "conversation_id": conversation_id,
        # Lead info
        "lead_name": "",
        "lead_profile": "",
        "lead_context": "",
        # Commercial state
        "is_interested": False,
        "is_purchased": False,
        "payment_tier_sent": 0,
        "external_id": "",
        # Media context
        "last_media_type": "",
        "last_media_url": "",
        "last_media_content_type": "",
        "last_media_summary": "",
        "last_media_synthetic_text": "",
        "last_media_received_at": "",
        # Qualification & engagement
        "engagement_score": 0,
        "content_seen": False,
        "is_qualified": False,
        "intro_sent": False,
        "experiencia_sent": False,
        "mentoria_sent": False,
        "motivation_question_sent": False,
        # Objection handling automations
        "precisa_computador_sent": False,
        "tempo_resultados_sent": False,
        "tempo_livre_sent": False,
        "experiencias_ruins_sent": False,
        "tem_medo_sent": False,
        "tem_profissao_sent": False,
        "outro_pais_sent": False,
        "e_mae_sent": False,
        "faz_faculdade_sent": False,
        "e_crista_sent": False,
        "como_sei_seguro_sent": False,
        "comecando_do_zero_sent": False,
        "preciso_pagar_sent": False,
        "vai_ver_sent": False,
        # Negotiation
        "lead_budget": 0.0,
        "negotiated_amount": 0.0,
        "challenge_offered": False,
        # Follow-up tracking (v2 - multi-flow)
        "last_lead_message_at": "",
        "follow_up_flow": 0,            # 0=nenhum, 1=pré-automação1, 2=pós-automação1, 3=pós-automação2
        "follow_up_flow_count": 0,
        "follow_up_flow_started_at": "",
        "follow_up_flow_anchor": "",
        "follow_up_expired": False,
        # Flags por follow-up enviado (anti-duplicação)
        # Fluxo 1
        "follow_1_1_sent": False,
        "follow_1_2_sent": False,
        "follow_1_3_sent": False,
        "follow_1_4_sent": False,
        # Fluxo 2
        "follow_2_1_sent": False,
        "follow_2_2_sent": False,
        "follow_2_3_sent": False,
        # Fluxo 3
        "follow_3_1_sent": False,
        "follow_3_2_sent": False,
        "follow_3_3_sent": False,
        # Automation flags
        "automation_1_sent": False,
        "automation_2_sent": False,
        # Janela 24h
        "lead_first_contact_at": "",
        "follow_janela_24h_sent": False,
    }
    ctx = SessionContext(state)
    automation = DataCrazyAutomationClient()

    all_tools = build_vanessa_tools(ctx, automation)
    prompt = build_system_prompt()

    return Agent(
        name="Vanessa",
        id="vanessa-vfo-agent",
        session_id=session_id,
        model=build_model(),
        tools=all_tools,
        session_state=state,
        db=SqliteDb(db_file=SESSION_DB_PATH),
        add_history_to_context=True,
        num_history_runs=10,
        description=prompt["description"],
        instructions=prompt["instructions"],
        tool_call_limit=5,
        markdown=False,
    )
