"""Resolve API endpoints for ingest caption (VLM) models."""

from __future__ import annotations

from app.config import Settings


def caption_api_base_url(settings: Settings) -> str:
    return settings.ingest_caption_api_base_url or settings.llm_api_base_url


def caption_api_key(settings: Settings) -> str:
    return settings.ingest_caption_api_key or settings.llm_api_key


def caption_model_name(settings: Settings) -> str:
    return settings.ingest_caption_model or settings.llm_model
