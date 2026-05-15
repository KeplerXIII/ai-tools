from __future__ import annotations

"""Юнит-тесты эндпоинтов parsing (источники, разбор, деактивация).

Что проверяется
    Поведение функций FastAPI-эндпоинтов ``create_source``, ``deactivate_source``,
    ``parse_source`` (постановка в очередь, 404), ``list_sources`` и логика
    ``execute_parse_source`` в ``parse_source_runner``: коды ошибок, подсчёты
    ``found_total`` / ``created_total``, лимит параллельного извлечения статей.

Как устроено тестирование (без HTTP и без реальной БД)
    - Эндпоинты вызываются напрямую как асинхронные функции с явной передачей
      ``db`` и ``user``, без ``TestClient`` и без поднятого сервера.
    - ``_FakeDb`` имитирует минимальный контракт async-сессии SQLAlchemy
      (``get``, ``execute``, ``commit``, ``scalar``, ``begin`` и т.д.): данные
      живут в памяти процесса, драйвер PostgreSQL не используется.
    - ``SimpleNamespace`` играет роль строки источника/пользователя там, где
      достаточно набора полей для ветвления в коде.
    - Сетевые и «тяжёлые» зависимости подменяются ``unittest.mock.patch`` и
      ``AsyncMock``: обнаружение URL, извлечение текста статьи, создание
      документа, справочники статусов/языка/страны. Так проверяется оркестрация
      и бизнес-ветки, а не реальный HTTP, RSS или запись в таблицы.

Ограничения
    Эти тесты не заменяют интеграционные: они не гарантируют корректность SQL,
    миграций, таймаутов внешних API и поведения прод-парсеров. Для этого нужны
    отдельные тесты с тестовой БД и/или контрактами к внешним сервисам.

См. также
    ``tests/conftest.py`` — переменные окружения для ``Settings`` при импорте
    приложения во время прогона pytest.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.v1.endpoints.parsing import (
    create_source,
    deactivate_source,
    list_active_source_parse_runs,
    list_countries_catalog,
    list_languages_catalog,
    list_sources,
    parse_source,
    update_source,
)
from app.schemas.parsing import ParseSourceRequest, SourceCreateRequest, SourceUpdateRequest
from app.services.parsing.parse_source_runner import execute_parse_source
from app.services.parsing.source_discovery import DiscoveredUrl


class _FakeResult:
    """Заглушка результата execute/scalars для цепочек ORM в тестах."""

    def __iter__(self):
        return iter([])

    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDb:
    """In-memory двойник async Session: отдаёт заданный ``source`` из ``get``, считает ``execute``."""

    def __init__(self, source):
        self._source = source
        self.insert_calls = 0
        self._added = None

    async def get(self, model, item_id):
        if self._source is not None and item_id == self._source.id:
            return self._source
        return None

    async def execute(self, statement):
        self.insert_calls += 1
        text = str(statement).lower()
        if "document_types" in text and "name" in text and "code" in text:
            class _DocTypeRow:
                def one(self):
                    return ("news", "Новость")

            return _DocTypeRow()
        if "document_types" in text and "code" in text:
            class _DocTypeCode:
                def one_or_none(self):
                    return ("news",)

            return _DocTypeCode()
        _ = statement
        return _FakeResult()

    async def rollback(self):
        return None

    def add(self, item):
        self._added = item

    async def commit(self):
        if self._added is not None and getattr(self._added, "id", None) is None:
            self._added.id = uuid.uuid4()
        return None

    async def refresh(self, item):
        _ = item
        return None

    async def scalar(self, statement):
        text = str(statement)
        if "SELECT languages.code" in text:
            return "en"
        if "SELECT countries.code" in text:
            return None
        return None

    @asynccontextmanager
    async def begin(self):
        yield self


class _FakeExecuteResult:
    """Результат ``execute`` со списком строк для ``list_sources``."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDbListSources:
    """Сессия, возвращающая заранее заданные строки выборки источников."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, statement):
        _ = statement
        return _FakeExecuteResult(self._rows)


class _FakeScalarsLang:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeExecLang:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalarsLang(self._items)


class _FakeDbLangCatalog:
    def __init__(self, items):
        self._items = items

    async def execute(self, statement):
        _ = statement
        return _FakeExecLang(self._items)


class _FakeScalarsParseRuns:
    def __init__(self, runs):
        self._runs = runs

    def all(self):
        return self._runs


class _FakeExecParseRuns:
    def __init__(self, runs):
        self._runs = runs

    def scalars(self):
        return _FakeScalarsParseRuns(self._runs)


class _FakeDbActiveParseRuns:
    """Для ``list_active_source_parse_runs``: ``execute().scalars().all()``."""

    def __init__(self, runs):
        self._runs = runs

    async def execute(self, statement):
        _ = statement
        return _FakeExecParseRuns(self._runs)


class ParseSourceEndpointTests(IsolatedAsyncioTestCase):
    """Сценарии вокруг ``deactivate_source``, ``parse_source``, ``create_source``."""

    async def test_deactivate_source_happy_path(self):
        """Деактивация своего источника: ``ok``, id в ответе, ``is_active`` сброшен."""
        source_id = uuid.uuid4()
        user_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            user_id=user_id,
            is_active=True,
        )
        db = _FakeDb(source=source)
        user = SimpleNamespace(id=user_id)

        result = await deactivate_source(source_id=source_id, db=db, user=user)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source_id"], str(source_id))
        self.assertFalse(result["is_active"])
        self.assertFalse(source.is_active)

    async def test_deactivate_source_returns_404_when_source_missing(self):
        """Нет источника в БД (фейковой) — HTTP 404."""
        db = _FakeDb(source=None)
        user = SimpleNamespace(id=uuid.uuid4())

        with self.assertRaises(HTTPException) as exc:
            await deactivate_source(source_id=uuid.uuid4(), db=db, user=user)

        self.assertEqual(exc.exception.status_code, 404)

    async def test_deactivate_source_returns_403_for_foreign_source(self):
        """Источник принадлежит другому пользователю — HTTP 403."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            user_id=uuid.uuid4(),
            is_active=True,
        )
        db = _FakeDb(source=source)
        user = SimpleNamespace(id=uuid.uuid4())

        with self.assertRaises(HTTPException) as exc:
            await deactivate_source(source_id=source_id, db=db, user=user)

        self.assertEqual(exc.exception.status_code, 403)

    async def test_parse_source_returns_404_when_source_missing(self):
        """``parse_source`` без найденного источника — HTTP 404."""
        db = _FakeDb(source=None)
        payload = ParseSourceRequest(source_id=uuid.uuid4(), days=3)

        with self.assertRaises(HTTPException) as exc:
            await parse_source(payload=payload, db=db, user=None)

        self.assertEqual(exc.exception.status_code, 404)

    async def test_parse_source_happy_path_response_shape(self):
        """Успешный прогон с моками: счётчики по двум найденным URL (логика в ``parse_source_runner``)."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            document_type_id=uuid.uuid4(),
            url="https://example.com",
            rss_url=None,
            is_active=True,
        )
        user = SimpleNamespace(id=uuid.uuid4())
        db = _FakeDb(source=source)

        url1 = "https://example.com/news/2026/05/01/a"
        url2 = "https://example.com/news/2026/05/02/b"
        discovered = [
            DiscoveredUrl(url=url1, published_at=datetime(2099, 5, 1, tzinfo=UTC)),
            DiscoveredUrl(url=url2, published_at=datetime(2099, 5, 2, tzinfo=UTC)),
        ]

        docs_created: list[SimpleNamespace] = []
        create_doc_kwargs: list[dict] = []

        async def _create_doc(*args, **kwargs):
            _ = args
            create_doc_kwargs.append(kwargs)
            doc = SimpleNamespace(
                id=uuid.uuid4(),
                version=1,
                source_id=None,
                published_at=None,
            )
            docs_created.append(doc)
            return doc

        with (
            patch(
                "app.services.parsing.parse_source_runner.discover_source_news_urls",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "app.services.parsing.parse_source_runner.get_document_by_source_url",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.parsing.parse_source_runner.extract_single_article_for_parse_source",
                AsyncMock(
                    return_value={
                        "title": "n",
                        "text": "body",
                        "length": 4,
                        "method": "m",
                        "quality": "good",
                        "needs_review": False,
                    }
                ),
            ),
            patch(
                "app.services.parsing.parse_source_runner.create_document_after_extract",
                AsyncMock(side_effect=_create_doc),
            ),
        ):
            outcome = await execute_parse_source(
                db,
                source_id=source_id,
                days=7,
                skip_undated=False,
                created_by_id=user.id,
            )

        self.assertEqual(outcome.found_total, 2)
        self.assertEqual(outcome.created_total, 2)
        self.assertEqual(len(create_doc_kwargs), 2)
        for kw in create_doc_kwargs:
            self.assertEqual(kw.get("document_type_code"), "news")
        for doc in docs_created:
            self.assertEqual(doc.source_id, source_id)

    async def test_parse_source_respects_extract_concurrency_limit(self):
        """Параллельные «извлечения» не превышают ожидаемый лимит (отслеживание через stub)."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            document_type_id=uuid.uuid4(),
            url="https://example.com",
            rss_url=None,
            is_active=True,
        )
        db = _FakeDb(source=source)
        discovered = [
            DiscoveredUrl(url=f"https://example.com/news/2026/05/0{i}/x{i}", published_at=None)
            for i in range(1, 9)
        ]

        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def _extract_stub(url: str, *, delay_sec: float, **kwargs):
            _ = url
            _ = delay_sec
            _ = kwargs
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            async with lock:
                in_flight -= 1
            return {
                "title": "t",
                "text": "body",
                "length": 4,
                "method": "m",
                "quality": "good",
                "needs_review": False,
            }

        async def _create_doc(*args, **kwargs):
            _ = args
            _ = kwargs
            return SimpleNamespace(id=uuid.uuid4(), version=1, source_id=None, published_at=None)

        with (
            patch(
                "app.services.parsing.parse_source_runner.discover_source_news_urls",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "app.services.parsing.parse_source_runner.get_document_by_source_url",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.parsing.parse_source_runner.extract_single_article_for_parse_source",
                AsyncMock(side_effect=_extract_stub),
            ),
            patch(
                "app.services.parsing.parse_source_runner.create_document_after_extract",
                AsyncMock(side_effect=_create_doc),
            ),
        ):
            await execute_parse_source(
                db,
                source_id=source_id,
                days=7,
                skip_undated=False,
                created_by_id=None,
            )

        self.assertLessEqual(max_in_flight, 3)

    async def test_parse_source_skips_when_extracted_date_older_than_depth(self):
        """После trafilatura отсекаем документ, если итоговая дата старше окна (UTC)."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            document_type_id=uuid.uuid4(),
            url="https://example.com",
            rss_url=None,
            is_active=True,
        )
        db = _FakeDb(source=source)
        discovered = [
            DiscoveredUrl(url="https://example.com/news/old", published_at=None),
        ]
        fixed_now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)

        create_calls = 0

        async def _create_doc(*args, **kwargs):
            nonlocal create_calls
            create_calls += 1
            return SimpleNamespace(id=uuid.uuid4(), version=1, source_id=None, published_at=None)

        with (
            patch(
                "app.services.parsing.parse_source_runner.discover_source_news_urls",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "app.services.parsing.parse_source_runner.get_document_by_source_url",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.parsing.parse_source_runner.datetime",
            ) as mock_dt,
            patch(
                "app.services.parsing.parse_source_runner.extract_single_article_for_parse_source",
                AsyncMock(
                    return_value={
                        "title": "n",
                        "text": "body",
                        "length": 4,
                        "method": "m",
                        "quality": "good",
                        "needs_review": False,
                        "date": "2026-04-01",
                    }
                ),
            ),
            patch(
                "app.services.parsing.parse_source_runner.create_document_after_extract",
                AsyncMock(side_effect=_create_doc),
            ),
        ):
            mock_dt.now = MagicMock(return_value=fixed_now)
            mock_dt.UTC = UTC
            outcome = await execute_parse_source(
                db,
                source_id=source_id,
                days=7,
                skip_undated=False,
                created_by_id=None,
            )

        self.assertEqual(create_calls, 0)
        self.assertEqual(outcome.created_total, 0)
        self.assertEqual(outcome.found_total, 1)

    async def test_parse_source_skips_when_skip_undated_and_no_final_date(self):
        """При skip_undated не сохраняем документ без итоговой даты публикации."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            document_type_id=uuid.uuid4(),
            url="https://example.com",
            rss_url=None,
            is_active=True,
        )
        db = _FakeDb(source=source)
        discovered = [
            DiscoveredUrl(url="https://example.com/news/nodate", published_at=None),
        ]
        create_calls = 0

        async def _create_doc(*args, **kwargs):
            nonlocal create_calls
            create_calls += 1
            return SimpleNamespace(id=uuid.uuid4(), version=1, source_id=None, published_at=None)

        with (
            patch(
                "app.services.parsing.parse_source_runner.discover_source_news_urls",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "app.services.parsing.parse_source_runner.get_document_by_source_url",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.parsing.parse_source_runner.extract_single_article_for_parse_source",
                AsyncMock(
                    return_value={
                        "title": "n",
                        "text": "body",
                        "length": 4,
                        "method": "m",
                        "quality": "good",
                        "needs_review": False,
                    }
                ),
            ),
            patch(
                "app.services.parsing.parse_source_runner.create_document_after_extract",
                AsyncMock(side_effect=_create_doc),
            ),
        ):
            outcome = await execute_parse_source(
                db,
                source_id=source_id,
                days=7,
                skip_undated=True,
                created_by_id=None,
            )

        self.assertEqual(create_calls, 0)
        self.assertEqual(outcome.created_total, 0)

    async def test_parse_source_does_not_filter_undated_during_discovery(self):
        """При skip_undated discovery не фильтрует бездатные ссылки до extraction."""
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            document_type_id=uuid.uuid4(),
            url="https://example.com",
            rss_url=None,
            is_active=True,
        )
        db = _FakeDb(source=source)
        discovered = [DiscoveredUrl(url="https://example.com/news/nodate", published_at=None)]
        discover_mock = AsyncMock(return_value=discovered)

        with (
            patch("app.services.parsing.parse_source_runner.discover_source_news_urls", discover_mock),
            patch(
                "app.services.parsing.parse_source_runner.get_document_by_source_url",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.parsing.parse_source_runner.extract_single_article_for_parse_source",
                AsyncMock(
                    return_value={
                        "title": "n",
                        "text": "body",
                        "length": 4,
                        "method": "m",
                        "quality": "good",
                        "needs_review": False,
                    }
                ),
            ),
            patch(
                "app.services.parsing.parse_source_runner.create_document_after_extract",
                AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), version=1, source_id=None, published_at=None)),
            ),
        ):
            await execute_parse_source(
                db,
                source_id=source_id,
                days=7,
                skip_undated=True,
                created_by_id=None,
            )

        discover_mock.assert_awaited_once()
        self.assertFalse(discover_mock.await_args.kwargs["skip_undated"])

    async def test_create_source_happy_path(self):
        """Создание источника: моки справочников языка/страны, проверка полей ответа."""
        db = _FakeDb(source=None)
        user = SimpleNamespace(id=uuid.uuid4())
        payload = SourceCreateRequest(
            url="https://example.com/",
            name="Example",
            language_code="en",
            country_code=None,
            rss_urls=["https://example.com/rss"],
            document_type_code="news",
        )
        with (
            patch("app.api.v1.endpoints.parsing._language_id_by_code", AsyncMock(return_value=uuid.uuid4())),
            patch("app.api.v1.endpoints.parsing._country_id_by_code", AsyncMock(return_value=None)),
            patch(
                "app.api.v1.endpoints.parsing.document_type_id_by_code",
                AsyncMock(return_value=uuid.uuid4()),
            ),
        ):
            result = await create_source(payload=payload, db=db, user=user)

        self.assertEqual(result.url, "https://example.com/")
        self.assertEqual(result.rss_url, "https://example.com/rss")
        self.assertEqual(result.rss_urls, ["https://example.com/rss"])
        self.assertEqual(result.language_code, "en")
        self.assertEqual(result.document_type_code, "news")
        self.assertEqual(result.document_type_name, "Новость")

    async def test_update_source_happy_path(self):
        """Обновление источника: поля в ответе и запись в памяти _FakeDb."""
        uid = uuid.uuid4()
        sid = uuid.uuid4()
        source = SimpleNamespace(
            id=sid,
            user_id=uid,
            document_type_id=uuid.uuid4(),
            name="Old",
            url="https://example.com/",
            country_id=None,
            language_id=uuid.uuid4(),
            rss_url=None,
            discovery_paths=None,
            is_active=True,
        )
        db = _FakeDb(source=source)
        user = SimpleNamespace(id=uid, is_admin=False)
        payload = SourceUpdateRequest(
            url="https://example.com/",
            name="New name",
            language_code="en",
            country_code=None,
            rss_urls=[
                "https://example.com/rss.xml",
                "https://example.com/rss2.xml",
            ],
            discovery_paths=["/news"],
            document_type_code="news",
        )
        with (
            patch("app.api.v1.endpoints.parsing._language_id_by_code", AsyncMock(return_value=uuid.uuid4())),
            patch("app.api.v1.endpoints.parsing._country_id_by_code", AsyncMock(return_value=None)),
            patch(
                "app.api.v1.endpoints.parsing.document_type_id_by_code",
                AsyncMock(return_value=uuid.uuid4()),
            ),
        ):
            result = await update_source(source_id=sid, payload=payload, db=db, user=user)

        self.assertEqual(result.name, "New name")
        self.assertEqual(result.rss_url, "https://example.com/rss.xml")
        self.assertEqual(
            result.rss_urls,
            ["https://example.com/rss.xml", "https://example.com/rss2.xml"],
        )
        self.assertEqual(result.discovery_paths, ["/news"])
        self.assertEqual(source.name, "New name")
        self.assertEqual(source.rss_urls, ["https://example.com/rss.xml", "https://example.com/rss2.xml"])
        self.assertEqual(source.discovery_paths, ["/news"])

    async def test_update_source_forbidden_for_other_user(self):
        """Чужой источник нельзя редактировать без прав администратора."""
        sid = uuid.uuid4()
        source = SimpleNamespace(
            id=sid,
            user_id=uuid.uuid4(),
            document_type_id=uuid.uuid4(),
            name=None,
            url="https://a.test/",
            is_active=True,
        )
        db = _FakeDb(source=source)
        user = SimpleNamespace(id=uuid.uuid4(), is_admin=False)
        payload = SourceUpdateRequest(
            url="https://a.test/",
            document_type_code="news",
        )
        with self.assertRaises(HTTPException) as ctx:
            await update_source(source_id=sid, payload=payload, db=db, user=user)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_list_sources_non_admin_response_shape(self):
        """Список источников для обычного пользователя: поля элемента и флаг фильтра."""
        uid = uuid.uuid4()
        sid = uuid.uuid4()
        created = datetime.now(UTC)
        src = SimpleNamespace(
            id=sid,
            user_id=uid,
            name="News",
            url="https://news.example/",
            rss_url="https://news.example/rss",
            rss_urls=["https://news.example/rss"],
            discovery_paths=["/news"],
            is_active=True,
            created_at=created,
            last_parse_created_total=2,
            last_parse_at=datetime.now(UTC),
        )
        db = _FakeDbListSources([(src, "alice", "de", "DE", "news", "Новость", 12, 3)])
        user = SimpleNamespace(id=uid, is_admin=False)
        result = await list_sources(db=db, user=user, added_by_user_id=None)
        self.assertFalse(result.can_filter_by_all_users)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].source_id, sid)
        self.assertEqual(result.items[0].added_by_username, "alice")
        self.assertEqual(result.items[0].language_code, "de")
        self.assertEqual(result.items[0].country_code, "DE")
        self.assertEqual(result.items[0].document_type_code, "news")
        self.assertEqual(result.items[0].document_type_name, "Новость")
        self.assertEqual(result.items[0].documents_total, 12)
        self.assertEqual(result.items[0].documents_unprocessed, 3)
        self.assertEqual(result.items[0].last_parse_created_total, 2)
        self.assertEqual(result.items[0].discovery_paths, ["/news"])
        self.assertEqual(result.items[0].rss_urls, ["https://news.example/rss"])

    async def test_list_sources_admin_sets_filter_flag(self):
        """Администратор получает возможность фильтрации по всем пользователям (флаг в ответе)."""
        uid = uuid.uuid4()
        src = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uid,
            name=None,
            url="https://a.test/",
            rss_url=None,
            discovery_paths=None,
            is_active=False,
            created_at=datetime.now(UTC),
            last_parse_created_total=None,
            last_parse_at=None,
        )
        db = _FakeDbListSources([(src, "bob", "en", None, "article", "Статья", 0, 0)])
        user = SimpleNamespace(id=uuid.uuid4(), is_admin=True)
        result = await list_sources(db=db, user=user, added_by_user_id=None)
        self.assertTrue(result.can_filter_by_all_users)
        self.assertFalse(result.items[0].is_active)

    async def test_list_languages_catalog_maps_rows(self):
        """Каталог языков: код и имя из строк ORM (порядок как отдал ``execute``)."""
        items = [
            SimpleNamespace(code="ru", name="Russian"),
            SimpleNamespace(code="en", name="English"),
        ]
        db = _FakeDbLangCatalog(items)
        result = await list_languages_catalog(db=db)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].code, "ru")
        self.assertEqual(result[0].name, "Russian")
        self.assertEqual(result[1].code, "en")

    async def test_list_countries_catalog_maps_rows(self):
        """Каталог стран: код и имя из строк ORM."""
        items = [
            SimpleNamespace(code="DE", name="Germany"),
            SimpleNamespace(code="US", name="United States"),
        ]
        db = _FakeDbLangCatalog(items)
        result = await list_countries_catalog(db=db)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].code, "DE")
        self.assertEqual(result[0].name, "Germany")
        self.assertEqual(result[1].code, "US")

    async def test_list_active_parse_runs_empty(self):
        """Нет активных запусков — пустой список."""
        db = _FakeDbActiveParseRuns([])
        user = SimpleNamespace(id=uuid.uuid4(), is_admin=False)
        result = await list_active_source_parse_runs(db=db, user=user)
        self.assertEqual(result.items, [])

    async def test_list_active_parse_runs_one_pending(self):
        """Один pending-запуск: в ответе source_id и статус разбора."""
        rid = uuid.uuid4()
        sid = uuid.uuid4()
        run = SimpleNamespace(
            id=rid,
            source_id=sid,
            status="pending",
            processing_job_id=None,
            phase="queued",
            found_total=None,
            created_total=None,
            new_document_ids=None,
            error_message=None,
            started_at=None,
            finished_at=None,
        )
        db = _FakeDbActiveParseRuns([run])
        user = SimpleNamespace(id=uuid.uuid4(), is_admin=False)
        result = await list_active_source_parse_runs(db=db, user=user)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].source_id, sid)
        self.assertEqual(result.items[0].parse_run.parse_run_id, rid)
        self.assertEqual(result.items[0].parse_run.status, "pending")

    async def test_list_active_parse_runs_dedupes_by_source(self):
        """Два запуска по одному источнику — в ответе только первый по ``created_at`` (новее)."""
        sid = uuid.uuid4()
        older = datetime(2020, 1, 1, tzinfo=UTC)
        newer = datetime(2025, 1, 1, tzinfo=UTC)
        run_old = SimpleNamespace(
            id=uuid.uuid4(),
            source_id=sid,
            status="pending",
            processing_job_id=None,
            phase="queued",
            found_total=None,
            created_total=None,
            new_document_ids=None,
            error_message=None,
            started_at=None,
            finished_at=None,
            created_at=older,
        )
        run_new = SimpleNamespace(
            id=uuid.uuid4(),
            source_id=sid,
            status="running",
            processing_job_id=None,
            phase="extract",
            found_total=5,
            created_total=None,
            new_document_ids=None,
            error_message=None,
            started_at=None,
            finished_at=None,
            created_at=newer,
        )
        db = _FakeDbActiveParseRuns([run_new, run_old])
        user = SimpleNamespace(id=uuid.uuid4(), is_admin=False)
        result = await list_active_source_parse_runs(db=db, user=user)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].parse_run.parse_run_id, run_new.id)
        self.assertEqual(result.items[0].parse_run.status, "running")
