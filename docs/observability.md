# Backend observability

AllDocs emits one-line JSON logs. HTTP logs include `request_id`; tasks scheduled by an
HTTP request carry that ID in their Celery headers, so worker logs contain both
`request_id` and `task_id`. Clients may supply `X-Request-ID`; otherwise the API creates
one and always returns it in the response header.

## Health endpoints

| Endpoint | Service | Response |
|----------|---------|----------|
| `GET /health` | API | `{ "status": "ok", "speech_ready": bool }` — `speech_ready` indicates Whisper/Piper loaded |
| `GET /ready` | Inference | Readiness probe (models loaded) |
| `GET /metrics` | API, Inference | Prometheus text format |

## Prometheus scrape targets

The Docker Compose network exposes these internal targets:

- `api:8000/metrics`
- `inference:8100/metrics`
- `worker-ingestion:9100`
- `worker-maintenance:9100`

Worker metric ports are internal-only by default. Set `METRICS_ENABLED=false` to disable
metrics or change `METRICS_WORKER_PORT` consistently in the environment and scraper.

Workers use multiprocess Prometheus collection; Compose sets `PROMETHEUS_MULTIPROC_DIR`
(default `/tmp/alldocs-prometheus` in `observability.py`).

Primary metrics:

- `alldocs_http_requests_total`
- `alldocs_http_request_duration_seconds`
- `alldocs_http_requests_in_progress`
- `alldocs_celery_tasks_total`
- `alldocs_celery_task_duration_seconds`
- `alldocs_stage_duration_seconds`

## Stage histogram (`alldocs_stage_duration_seconds`)

Labels: `component`, `stage`. Observed durations include:

| Component | Stages |
|-----------|--------|
| `ingestion` | `external_stores`, `download`, `parse_document`, `clear_previous_index`, `upload_assets`, `persist_chunks`, `embedding`, `qdrant_upsert`, `elasticsearch_upsert` |
| `maintenance` | `delete_external_stores`, `finalize_deletion` |
| `rag` | `embed_query`, `embed_queries`, `rerank`, `hybrid_search`, `load_chunks` |
| `inference` | `embed_queries`, `embed_documents`, `rerank` |

## Inference HTTP API

When `INFERENCE_URL` is set, api/worker call the inference service instead of loading BGE locally:

- `POST /v1/embed/queries`
- `POST /v1/embed/documents`
- `POST /v1/rerank`
