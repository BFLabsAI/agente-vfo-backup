from __future__ import annotations

from app.config import OMNIROUTE_API_KEY, OMNIROUTE_BASE_URL, OMNIROUTE_MODEL_ID


def build_model(model_id: str | None = None):
    """
    OmniRoute is OpenAI-compatible — use OpenAIChat with custom base_url and api_key.
    Model IDs: "mimo/mimo-v2.5-pro", etc.
    """
    from agno.models.openai import OpenAIChat
    return OpenAIChat(
        id=model_id or OMNIROUTE_MODEL_ID,
        base_url=OMNIROUTE_BASE_URL,
        api_key=OMNIROUTE_API_KEY,
    )
