"""Resolve API endpoints for text vs vision/caption models."""

from __future__ import annotations

from app.config import Settings


def vision_api_base_url(settings: Settings) -> str:
    return settings.llm_vision_api_base_url or settings.llm_api_base_url


def vision_api_key(settings: Settings) -> str:
    return settings.llm_vision_api_key or settings.llm_api_key


def caption_api_base_url(settings: Settings) -> str:
    return (
        settings.ingest_caption_api_base_url
        or settings.llm_vision_api_base_url
        or settings.llm_api_base_url
    )


def caption_api_key(settings: Settings) -> str:
    return (
        settings.ingest_caption_api_key
        or settings.llm_vision_api_key
        or settings.llm_api_key
    )


def vision_model_name(settings: Settings) -> str:
    return settings.llm_vision_model or settings.llm_model


def caption_model_name(settings: Settings) -> str:
    return (
        settings.ingest_caption_model
        or settings.llm_vision_model
        or settings.llm_model
    )
