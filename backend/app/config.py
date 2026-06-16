from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_vision_enabled: bool = False
    llm_vision_api_base_url: str = ""
    llm_vision_api_key: str = ""
    llm_vision_model: str = ""
    llm_vision_max_images: int = 4
    llm_vision_render_scale: float = 2.0

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    embedding_batch_size: int = 8

    rag_retrieve_k: int = 20
    rag_top_k: int = 5
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 80
    rag_neighbor_window: int = 1
    rag_agent_max_steps: int = 7
    rag_agent_max_retrievals: int = 6
    rag_batch_search_max: int = 4

    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cpu"
    rerank_batch_size: int = 8
    rag_min_rerank_score: float = 0.0
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

    ingest_caption_enabled: bool = False
    ingest_caption_api_base_url: str = ""
    ingest_caption_api_key: str = ""
    ingest_caption_model: str = ""
    ingest_caption_max_per_doc: int = 20
    ingest_caption_min_text_chars: int = 50

    app_host: str = "0.0.0.0"
    app_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
