"""Оркестрация сидов справочников после миграций.

Данные лежат в отдельных модулях (``roles``, ``languages``, …); здесь только
порядок вызовов. CLI: ``python -m app.cli.seed_reference_data``.

Идемпотентность: конфликт по уникальному ``code``/``name`` обновляет поля,
существующий ``id`` не меняется; для вставок задаётся ``uuid.uuid4()`` (см. ``util``).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.seeds.categories import apply_categories_seed
from app.seeds.countries import apply_countries_seed
from app.seeds.document_types import apply_document_types_seed
from app.seeds.embedding_models import apply_embedding_models_seed
from app.seeds.entity_types import apply_entity_types_seed
from app.seeds.environments import apply_environments_seed
from app.seeds.funds import apply_funds_seed
from app.seeds.languages import apply_languages_seed
from app.seeds.prediction_sources import apply_prediction_sources_seed
from app.seeds.roles import apply_roles_seed, apply_user_admin_roles


async def seed_reference_catalog(session: AsyncSession) -> dict[str, int]:
    """Идемпотентно заполняет справочники и связывает admin-пользователей с ролью admin."""
    out: dict[str, int] = {}
    out["roles"] = await apply_roles_seed(session)
    out["languages"] = await apply_languages_seed(session)
    out["countries"] = await apply_countries_seed(session)
    out["prediction_sources"] = await apply_prediction_sources_seed(session)
    out["entity_types"] = await apply_entity_types_seed(session)
    out["embedding_models"] = await apply_embedding_models_seed(session)
    out["environments"] = await apply_environments_seed(session)
    out["funds"] = await apply_funds_seed(session)
    out["categories"] = await apply_categories_seed(session)
    out["document_types"] = await apply_document_types_seed(session)
    await apply_user_admin_roles(session)
    return out
