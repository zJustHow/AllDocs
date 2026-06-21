# Backend observability

AllDocs emits one-line JSON logs. HTTP logs include `request_id`; tasks scheduled by an
HTTP request carry that ID in their Celery headers, so worker logs contain both
`request_id` and `task_id`. Clients may supply `X-Request-ID`; otherwise the API creates
one and always returns it in the response header.

## Prometheus scrape targets

The Docker Compose network exposes these internal targets:

- `api:8000/metrics`
- `inference:8100/metrics`
- `worker-ingestion:9100`
- `worker-maintenance:9100`

Worker metric ports are internal-only by default. Set `METRICS_ENABLED=false` to disable
metrics or change `METRICS_WORKER_PORT` consistently in the environment and scraper.

Primary metrics:

- `alldocs_http_requests_total`
- `alldocs_http_request_duration_seconds`
- `alldocs_http_requests_in_progress`
- `alldocs_celery_tasks_total`
- `alldocs_celery_task_duration_seconds`
- `alldocs_stage_duration_seconds`

The stage histogram covers document download, parsing, asset upload, chunk persistence,
embedding, Qdrant/Elasticsearch writes, RAG retrieval, and inference operations.
