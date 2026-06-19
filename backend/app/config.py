from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    inference_url: str = ""
    inference_timeout_seconds: float = 120.0
    inference_batch_wait_ms: int = 10
    inference_batch_max_texts: int = 64

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 8

    rag_retrieve_k: int = 10
    rag_top_k: int = 3
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    rag_agent_max_steps: int = 10
    rag_agent_max_retrievals: int = 6
    rag_batch_search_max: int = 3

    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cpu"
    rerank_batch_size: int = 8
    rag_min_rerank_score: float = -1.5
    rag_min_retrieval_score: float = 0.015

    postgres_url: str = "postgresql+asyncpg://alldocs:alldocs@localhost:5432/alldocs"
    postgres_url_sync: str = "postgresql://alldocs:alldocs@localhost:5432/alldocs"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "manual_chunks"

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "manual_chunks"
    hybrid_enabled: bool = True
    hybrid_rrf_k: int = 60

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "manuals"
    minio_secure: bool = False

    whisper_model: str = "large-v3"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    piper_model_dir: str = "./models/piper"
    piper_zh_model: str = "zh_CN-huayan-medium"
    piper_en_model: str = "en_US-lessac-medium"

    ocr_enabled: bool = True
    ocr_lang: str = "ch"
    ocr_force: bool = False
    ocr_min_chars_per_page: int = 30
    ocr_render_scale: float = 2.0

    pdf_extract_embedded_images: bool = True
    pdf_embedded_image_min_width: int = 64
    pdf_embedded_image_min_height: int = 64
    pdf_embedded_image_max_page_coverage: float = 0.85
    pdf_embedded_image_max_per_page: int = 20

    pdf_extract_tables: bool = True
    pdf_table_min_rows: int = 2
    pdf_table_min_cols: int = 2
    pdf_table_render_scale: float = 2.0

    pdf_filter_header_footer: bool = True
    pdf_header_margin_ratio: float = 0.08
    pdf_footer_margin_ratio: float = 0.08
    pdf_hf_min_repeat_pages: int = 3
    pdf_hf_min_repeat_ratio: float = 0.35

    ingest_caption_enabled: bool = False
    ingest_caption_api_base_url: str = ""
    ingest_caption_api_key: str = ""
    ingest_caption_model: str = ""
    ingest_caption_max_per_doc: int = 20

    rag_step_align_min_score: float = 0.42

    embed_skip_table_when_answer_has_markdown: bool = True
    embed_skip_table_lookback: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
