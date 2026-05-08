from __future__ import annotations

from app.core.config import settings as app_settings
from app.services.processing.saq_queue import get_saq_categorize_queue
from app.services.processing.saq_tasks import categorize_document_job

worker_settings = {
    "queue": get_saq_categorize_queue(),
    "functions": [categorize_document_job],
    "concurrency": app_settings.saq_categorize_worker_concurrency,
}

# SAQ CLI expects `<module>.settings`.
settings = worker_settings
