from __future__ import annotations

from app.core.config import settings as app_settings
from app.services.processing.saq_queue import get_saq_annotate_queue
from app.services.processing.saq_tasks import annotate_document_job

worker_settings = {
    "queue": get_saq_annotate_queue(),
    "functions": [annotate_document_job],
    "concurrency": app_settings.saq_annotate_worker_concurrency,
}

# SAQ CLI expects `<module>.settings`.
settings = worker_settings
