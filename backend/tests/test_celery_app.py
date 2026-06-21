from app.workers.celery_app import (
    INGESTION_QUEUE,
    MAINTENANCE_QUEUE,
    celery_app,
)


def test_document_tasks_are_routed_to_dedicated_queues() -> None:
    routes = celery_app.conf.task_routes

    assert routes["process_document"]["queue"] == INGESTION_QUEUE
    assert routes["delete_document"]["queue"] == MAINTENANCE_QUEUE


def test_unrouted_tasks_fall_back_to_maintenance_queue() -> None:
    assert celery_app.conf.task_default_queue == MAINTENANCE_QUEUE
