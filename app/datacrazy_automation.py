from __future__ import annotations

import json
import logging
import unicodedata
import asyncio
from pathlib import Path
from typing import Any

import httpx

from app.config import DATACRAZY_API_TOKEN

logger = logging.getLogger("vanessa.automation")


def _sanitize_text(text: str) -> str:
    """
    Sanitize text to prevent mojibake (corrupted characters).
    Normalizes Unicode and replaces common problematic patterns.
    """
    if not text:
        return text

    # Normalize to NFC form (composed characters)
    text = unicodedata.normalize("NFC", text)

    # Replace Unicode replacement character (U+FFFD) which indicates encoding errors
    # Try to recover the original character based on common mojibake patterns
    replacements = {
        "\ufffdã": "ã",
        "\ufffdõ": "õ",
        "\ufffdç": "ç",
        "\ufffdá": "á",
        "\ufffdé": "é",
        "\ufffdí": "í",
        "\ufffdó": "ó",
        "\ufffdú": "ú",
        "\ufffdâ": "â",
        "\ufffdê": "ê",
        "\ufffdî": "î",
        "\ufffdô": "ô",
        "\ufffdû": "û",
        "\ufffdà": "à",
        "\ufffdè": "è",
        "\ufffdì": "ì",
        "\ufffdò": "ò",
        "\ufffdù": "ù",
        "\ufffdä": "ä",
        "\ufffdë": "ë",
        "\ufffdï": "ï",
        "\ufffdö": "ö",
        "\ufffdü": "ü",
        "\ufffdñ": "ñ",
        "\ufffdÁ": "Á",
        "\ufffdÉ": "É",
        "\ufffdÍ": "Í",
        "\ufffdÓ": "Ó",
        "\ufffdÚ": "Ú",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Remove any remaining standalone replacement characters
    text = text.replace("\ufffd", "")

    return text


class DataCrazyAutomationClient:
    """
    Dispara automações do DataCrazy via webhook para enviar mídia nativa no WhatsApp.
    Instancia-aware: seleciona webhooks corretos com base no DATACRAZY_INSTANCE_ID.
    """

    # ── Instância 1 (número original) ──────────────────────────────────────
    # ── Webhooks de automação ──────────────────────────────────────────────
    # As URLs de gatilho do CRM são específicas da conta e não são versionadas.
    # Copie config/datacrazy_webhooks.example.json para
    # config/datacrazy_webhooks.json e preencha com as URLs da sua instância.
    _WEBHOOKS_FILE = Path(__file__).resolve().parent.parent / "config" / "datacrazy_webhooks.json"

    @staticmethod
    def _load_webhooks() -> dict[str, dict]:
        path = DataCrazyAutomationClient._WEBHOOKS_FILE
        if not path.is_file():
            logger.warning(
                "datacrazy_webhooks.json ausente em %s — automações de webhook desativadas. "
                "Use config/datacrazy_webhooks.example.json como modelo.", path)
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("instancias", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Falha ao ler %s: %s", path, exc)
            return {}

    AUTOMATION_BASE_URL = "https://api.datacrazy.io"

    def __init__(self, token: str | None = None, instance_id: str | None = None) -> None:
        from app.config import DATACRAZY_INSTANCE_ID
        self._token = token or DATACRAZY_API_TOKEN
        self._instance_id = instance_id or DATACRAZY_INSTANCE_ID
        # Select webhooks for this instance (fallback to v1 if unknown)
        self._instance_map = self._load_webhooks()
        self.AUTOMATION_WEBHOOKS = self._instance_map.get(self._instance_id, {})
        logger.info("DataCrazyAutomationClient | instance_id=%s webhooks=%d",
                    self._instance_id, len(self.AUTOMATION_WEBHOOKS))
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def trigger_automation(self, automation_key: str, conversation_id: str, contact_id: str = "", external_id: str = "") -> dict[str, Any]:
        """
        Dispara uma automação do DataCrazy via webhook.
        """
        url = self.AUTOMATION_WEBHOOKS.get(automation_key)
        # Fallback: if v2 URL is empty, use v1
        if not url:
            fallback = next(iter(self._instance_map.values()), {})
            url = fallback.get(automation_key)
            if url:
                logger.warning("trigger_automation | key=%s empty in v2, falling back to v1", automation_key)
        if not url:
            raise ValueError(f"Automation key '{automation_key}' not found")

        # Clean IDs — DataCrazy sometimes sends lead_id with extra quotes/braces like ""{uuid}"
        clean_lead_id = external_id.strip().strip('"').strip("'").strip('{').strip('}').strip()
        clean_conv_id = conversation_id.strip()
        clean_contact_id = contact_id.strip()

        # DataCrazy webhook expects lead_id (externalId) to identify the contact
        payload = {
            "lead_id": clean_lead_id,
            "conversation_id": clean_conv_id,
            "contactId": clean_contact_id,
            "phone": clean_contact_id,
        }
        logger.info(
            "trigger_automation | key=%s conv=%s contact=%s lead_id=%s",
            automation_key, clean_conv_id, clean_contact_id, clean_lead_id,
        )

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("trigger_automation | success key=%s", automation_key)
            return {"status": "success", "automation_key": automation_key, "response": data}
        except httpx.HTTPStatusError as e:
            logger.error("trigger_automation | HTTP %s key=%s: %s", e.response.status_code, automation_key, e.response.text)
            return {"status": "error", "automation_key": automation_key, "message": str(e)}
        except Exception as exc:
            logger.error("trigger_automation | failed key=%s: %s", automation_key, exc)
            return {"status": "error", "automation_key": automation_key, "message": str(exc)}
    async def send_text_message(self, conversation_id: str, body: str) -> dict[str, Any]:
        """
        Envia uma mensagem de texto via API REST do DataCrazy.
        Com retry automático (2 tentativas extras com backoff).
        """
        from app.config import DATACRAZY_BASE_URL
        url = f"{DATACRAZY_BASE_URL}/api/v1/conversations/{conversation_id}/messages"
        sanitized_body = _sanitize_text(body)
        if sanitized_body != body:
            logger.warning("send_text_message | text sanitized: original=%r sanitized=%r", body[:100], sanitized_body[:100])
        payload = {"body": sanitized_body}

        max_retries = 3
        backoff = [0, 30, 60]  # seconds between retries
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    await asyncio.sleep(backoff[attempt])
                    logger.info("send_text_message | retry attempt %d/%d", attempt + 1, max_retries)
                resp = await self._client.post(url, json=payload)
                resp.raise_for_status()
                result = resp.json()
                if attempt > 0:
                    logger.info("send_text_message | succeeded on attempt %d", attempt + 1)
                return {"status": "success", "type": "text", "response": result, "message_id": result.get("id", "")}
            except httpx.HTTPStatusError as exc:
                logger.warning("send_text_message | HTTP %d attempt %d: %s", exc.response.status_code, attempt + 1, exc.response.text[:200])
                if attempt == max_retries - 1:
                    return {"status": "error", "message": str(exc), "http_status": exc.response.status_code}
            except Exception as exc:
                logger.warning("send_text_message | error attempt %d: %s", attempt + 1, exc)
                if attempt == max_retries - 1:
                    return {"status": "error", "message": str(exc)}
        return {"status": "error", "message": "max retries exceeded"}

    async def aclose(self) -> None:
        await self._client.aclose()
