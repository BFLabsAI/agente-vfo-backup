"""Media processing for VFO agent — aligned with SDR (Marcos) architecture.

Handles audio, image, video, sticker, and document messages via:
  - Audio: Deepgram Nova-3 via OmniRoute /audio/transcriptions (same as SDR)
  - Image/Sticker: Vision cascade — mimo/mimo-v2.5 → gweb/gemini-2.5-flash
  - Video: Vision cascade (same as image)
  - Document (PDF): Native PDF for Gemini; pymupdf page→PNG for others

Design: same cascade, same models, same prompts as sdr-mais-um-passo/app.py.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from app.config import (
    OMNIROUTE_API_KEY,
    OMNIROUTE_AUDIO_MODEL_ID,
    OMNIROUTE_BASE_URL,
    OMNIROUTE_ENDPOINT,
    OMNIROUTE_MEDIA_MODEL_ID,
    OMNIROUTE_VISION_FALLBACK_MODEL,
)

logger = logging.getLogger(__name__)


# ── Text normalization ───────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    cleaned = (text or "").strip()
    for prefix in ("Transcrição:", "Transcricao:", "Descrição:", "Descricao:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


# ── Content-Type → media kind ────────────────────────────────────────────────

def _classify_media_kind(content_type: str) -> str:
    content_type = (content_type or "").strip().lower()
    if content_type.startswith("audio/"):
        return "audio"
    if content_type == "image/webp":
        return "sticker"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type == "application/pdf" or content_type.startswith("application/"):
        return "document"
    return "other"


# ── Download helper ──────────────────────────────────────────────────────────

async def _download_media(media_url: str) -> tuple[bytes, str]:
    logger.info("download_media | downloading from=%s", media_url[:120])
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "application/octet-stream").split(";")[0].strip().lower()
        logger.info("download_media | downloaded bytes=%d content_type=%s", len(resp.content), content_type)
        return resp.content, content_type


# ── Audio transcription via Deepgram Nova-3 (same as SDR) ────────────────────

async def _transcribe_audio_deepgram(
    media_bytes: bytes,
    content_type: str,
    source_url: str,
) -> str:
    """Transcribe audio using Deepgram Nova-3 via OmniRoute /audio/transcriptions.

    Same approach as sdr-mais-um-passo/app.py _multimodal_caller audio branch.
    """
    import tempfile

    base_url = OMNIROUTE_ENDPOINT.replace("/chat/completions", "")
    suffix = ".ogg" if "ogg" in content_type else ".mp3" if "mp3" in content_type else ".wav"
    tmp_path = None

    logger.info(
        "transcribe_audio | content_type=%s bytes=%d model=%s",
        content_type, len(media_bytes), OMNIROUTE_AUDIO_MODEL_ID,
    )

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(media_bytes)
            tmp_path = tmp.name

        async with httpx.AsyncClient(timeout=30) as client:
            with open(tmp_path, "rb") as audio_file:
                resp = await client.post(
                    f"{base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OMNIROUTE_API_KEY}"},
                    data={"model": OMNIROUTE_AUDIO_MODEL_ID, "language": "pt"},
                    files={"file": (os.path.basename(tmp_path), audio_file, "audio/mpeg")},
                )
            resp.raise_for_status()
            text = resp.json().get("text", "")
            logger.info("transcribe_audio | result length=%d", len(text))
            if not text:
                raise RuntimeError(
                    f"empty Deepgram transcription | content_type={content_type} source={source_url[:120]}"
                )
            return _normalize_text(text)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Vision cascade (image/video/document) — same as SDR ──────────────────────

_VISION_MODELS = [
    OMNIROUTE_MEDIA_MODEL_ID,           # mimo/mimo-v2.5 (multimodal, NOT pro)
    OMNIROUTE_VISION_FALLBACK_MODEL,    # gweb/gemini-2.5-flash
]

_VISION_QUESTION_IMG = (
    "Você recebeu esta imagem via WhatsApp. "
    "Descreva o conteúdo de forma objetiva e identifique qualquer informação relevante para o atendimento."
)
_VISION_QUESTION_STICKER = (
    "Você recebeu esta figurinha (sticker) via WhatsApp. "
    "Descreva o conteúdo de forma objetiva e identifique qualquer informação relevante para o atendimento."
)
_VISION_QUESTION_VIDEO = (
    "Você recebeu este vídeo via WhatsApp. "
    "Descreva o conteúdo de forma objetiva: o que acontece, quem aparece, o que é dito ou mostrado, "
    "e qualquer informação relevante para o atendimento."
)
_VISION_QUESTION_DOC = (
    "Você recebeu este documento via WhatsApp. "
    "Analise-o detalhadamente: faça um resumo completo, identifique os pontos principais, "
    "dados relevantes, datas, valores e qualquer informação útil para o atendimento."
)

# Phrases that indicate the model can't see the image → try next model
_CANT_SEE_PHRASES = (
    "não consigo visualizar",
    "indisponível aqui",
    "cannot view",
    "can't view",
    "unable to view",
    "image is not available",
    "(unavailable)",
    "não é possível visualizar",
    "não tenho acesso à imagem",
)


def _prepare_content_parts(file_bytes: bytes, mime_type: str, model: str) -> list[dict]:
    """Build content parts for a vision model request.

    - Images: image_url with base64 inline
    - PDF + Gemini: native PDF via image_url
    - PDF + non-Gemini: convert pages to PNG via pymupdf (max 10 pages, 150 DPI)
    - Video: image_url with base64 inline
    """
    is_pdf = mime_type == "application/pdf" or file_bytes[:4] == b"%PDF"
    is_video = mime_type.startswith("video/")
    uses_native_pdf = "gweb/" in model or "gemini" in model

    # Video: send as base64 url
    if is_video:
        b64 = base64.b64encode(file_bytes).decode()
        return [{"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}]

    # PDF + Gemini: native PDF support
    if is_pdf and uses_native_pdf:
        b64 = base64.b64encode(file_bytes).decode()
        return [{"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{b64}"}}]

    # PDF + non-Gemini: convert pages to PNG
    if is_pdf:
        try:
            import fitz  # pymupdf
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            parts = []
            for i, page in enumerate(doc):
                if i >= 10:
                    break
                b64 = base64.b64encode(page.get_pixmap(dpi=150).tobytes("png")).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            doc.close()
            if parts:
                return parts
        except ImportError:
            logger.warning("pymupdf not installed — cannot convert PDF pages, sending raw PDF")
        except Exception as exc:
            logger.warning("pymupdf PDF conversion failed: %s, sending raw PDF", exc)

    # Default: image (JPEG/PNG/etc)
    b64 = base64.b64encode(file_bytes).decode()
    return [{"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}]


async def _analyze_with_cascade(file_bytes: bytes, mime_type: str, question: str) -> str:
    """Try vision models in cascade order. Same logic as SDR's _analyze_with_cascade.

    Falls through to next model on:
      - HTTP 500+
      - Timeout
      - Model responds with "can't see" phrases
    """
    base_url = OMNIROUTE_ENDPOINT.replace("/chat/completions", "")
    api_key = OMNIROUTE_API_KEY
    last_error = None

    for model in _VISION_MODELS:
        try:
            parts = _prepare_content_parts(file_bytes, mime_type, model)
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": question}, *parts],
                }],
                "max_tokens": 4096,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code >= 500:
                last_error = f"{model}: HTTP {resp.status_code}"
                logger.warning("vision cascade: %s, trying next", last_error)
                continue
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"] or ""

            # Check if model says it can't see the image
            if any(p in text.lower() for p in _CANT_SEE_PHRASES):
                last_error = f"{model}: respondeu que não consegue ver"
                logger.warning("vision cascade: %s, trying next", last_error)
                continue

            logger.info("vision cascade: success with model=%s text_len=%d", model, len(text))
            return text

        except httpx.TimeoutException:
            last_error = f"{model}: timeout"
            logger.warning("vision cascade: %s, trying next", last_error)
        except Exception as exc:
            last_error = f"{model}: {exc}"
            logger.warning("vision cascade: %s, trying next", last_error)

    raise RuntimeError(f"all vision models failed — last error: {last_error}")


# ── Main entry point ─────────────────────────────────────────────────────────

async def process_media_url(media_url: str) -> dict[str, Any]:
    """Download media, classify by Content-Type, and produce a synthetic text payload.

    Routes:
      - audio → Deepgram Nova-3 transcription
      - image/sticker → Vision cascade (mimo/mimo-v2.5 → gemini-2.5-flash)
      - video → Vision cascade
      - document → Vision cascade (native PDF or pymupdf conversion)
    """
    media_bytes, content_type = await _download_media(media_url)
    media_kind = _classify_media_kind(content_type)

    try:
        # ── Audio: Deepgram Nova-3 (same as SDR) ──
        if media_kind == "audio":
            analysis = await _transcribe_audio_deepgram(media_bytes, content_type, media_url)
            return {
                "media_type": media_kind,
                "media_url": media_url,
                "media_content_type": content_type,
                "media_summary": analysis,
                "synthetic_text": f"[lead enviou um áudio]\nTranscrição: {analysis}",
            }

        # ── Image/Sticker: Vision cascade ──
        if media_kind in {"image", "sticker"}:
            question = _VISION_QUESTION_STICKER if media_kind == "sticker" else _VISION_QUESTION_IMG
            analysis = await _analyze_with_cascade(media_bytes, content_type, question)
            header = "[lead enviou uma figurinha]" if media_kind == "sticker" else "[lead enviou uma imagem]"
            return {
                "media_type": media_kind,
                "media_url": media_url,
                "media_content_type": content_type,
                "media_summary": analysis,
                "synthetic_text": f"{header}\nDescrição: {analysis}",
            }

        # ── Video: Vision cascade ──
        if media_kind == "video":
            analysis = await _analyze_with_cascade(media_bytes, content_type, _VISION_QUESTION_VIDEO)
            return {
                "media_type": media_kind,
                "media_url": media_url,
                "media_content_type": content_type,
                "media_summary": analysis,
                "synthetic_text": f"[lead enviou um vídeo]\nDescrição: {analysis}",
            }

        # ── Document (PDF): Vision cascade ──
        if media_kind == "document":
            analysis = await _analyze_with_cascade(media_bytes, content_type, _VISION_QUESTION_DOC)
            return {
                "media_type": media_kind,
                "media_url": media_url,
                "media_content_type": content_type,
                "media_summary": analysis,
                "synthetic_text": f"[lead enviou um documento]\nDescrição: {analysis}",
            }

        # ── Other/unsupported ──
        logger.warning("process_media_url | unsupported content_type=%s url=%s", content_type, media_url[:120])
        return {
            "media_type": "other",
            "media_url": media_url,
            "media_content_type": content_type,
            "media_summary": "",
            "synthetic_text": "[lead enviou uma mídia]",
        }

    except Exception as exc:
        logger.error(
            "process_media_url | failed kind=%s content_type=%s url=%s err=%s",
            media_kind, content_type, media_url[:120], exc, exc_info=True,
        )
        fallback_header = {
            "audio": "[lead enviou um áudio]",
            "sticker": "[lead enviou uma figurinha]",
            "image": "[lead enviou uma imagem]",
            "video": "[lead enviou um vídeo]",
            "document": "[lead enviou um documento]",
        }.get(media_kind, "[lead enviou uma mídia]")
        fallback_label = "Transcrição" if media_kind == "audio" else "Descrição"
        return {
            "media_type": media_kind if media_kind != "other" else "",
            "media_url": media_url,
            "media_content_type": content_type,
            "media_summary": "[mídia não analisada]",
            "synthetic_text": f"{fallback_header}\n{fallback_label}: [mídia não analisada]",
        }


async def transcribe_or_extract(media_url: str, media_type: str = "") -> str:
    """Compatibility helper that returns only the synthetic text summary."""
    info = await process_media_url(media_url)
    return info.get("synthetic_text") or info.get("media_summary") or ""
