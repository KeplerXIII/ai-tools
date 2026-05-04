"""SQLAdmin ModelView для доменных таблиц."""

from sqladmin import ModelView
from wtforms import PasswordField
from wtforms.validators import Length, Optional

from app.core.security import hash_password
from app.infrastructure.db.models import (
    Category,
    Country,
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentEmbedding,
    DocumentEntity,
    DocumentTag,
    DocumentType,
    EmbeddingModel,
    Entity,
    EntityType,
    Environment,
    Fund,
    Language,
    PredictionSource,
    ProcessingJob,
    Role,
    Source,
    Tag,
    User,
    UserRole,
)
from starlette.requests import Request


class UserAdmin(ModelView, model=User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"
    column_labels = {
        User.id: "ID",
        User.username: "Логин",
        User.email: "Email",
        User.hashed_password: "Пароль (хэш)",
        User.is_active: "Активен",
        User.is_admin: "Администратор",
        User.created_at: "Создан",
    }
    column_list = [User.id, User.username, User.email, User.is_active, User.is_admin, User.created_at]
    column_searchable_list = [User.username, User.email]
    column_sortable_list = [User.username, User.created_at]
    form_columns = [User.username, User.email, User.hashed_password, User.is_active, User.is_admin]
    form_overrides = {"hashed_password": PasswordField}
    form_args = {
        "username": {"label": "Логин"},
        "email": {"label": "Email"},
        "is_active": {"label": "Активен"},
        "is_admin": {"label": "Администратор"},
        "hashed_password": {
            "label": "Пароль",
            "description": "При создании — обязательно (от 8 символов). При редактировании оставьте пустым, чтобы не менять.",
            "validators": [Optional(), Length(min=8, max=128)],
        },
    }
    can_create = True
    can_delete = True

    async def on_model_change(
        self,
        data: dict,
        model: User,
        is_created: bool,
        request: Request,
    ) -> None:
        if "username" in data and isinstance(data["username"], str):
            data["username"] = data["username"].strip().lower()

        if data.get("email") == "":
            data["email"] = None

        raw_pw = data.get("hashed_password")
        if isinstance(raw_pw, str):
            raw_pw = raw_pw.strip()
        else:
            raw_pw = ""

        if raw_pw:
            data["hashed_password"] = hash_password(raw_pw)
        else:
            data.pop("hashed_password", None)
            if is_created:
                raise ValueError("При создании пользователя укажите пароль (не короче 8 символов).")


class RoleAdmin(ModelView, model=Role):
    name = "Роль"
    name_plural = "Роли"
    icon = "fa-solid fa-id-badge"
    column_list = [Role.id, Role.code, Role.name]


class UserRoleAdmin(ModelView, model=UserRole):
    name = "Роль пользователя"
    name_plural = "Роли пользователей"
    icon = "fa-solid fa-user-tag"
    column_list = [UserRole.user_id, UserRole.role_id]


class LanguageAdmin(ModelView, model=Language):
    name = "Язык"
    name_plural = "Языки"
    column_list = [Language.id, Language.code, Language.name]


class CountryAdmin(ModelView, model=Country):
    name = "Страна"
    name_plural = "Страны"
    column_list = [Country.id, Country.code, Country.name]


class PredictionSourceAdmin(ModelView, model=PredictionSource):
    name = "Источник предсказания"
    name_plural = "Источники предсказаний"
    column_list = [PredictionSource.id, PredictionSource.code, PredictionSource.name, PredictionSource.is_active]


class DocumentTypeAdmin(ModelView, model=DocumentType):
    name = "Тип документа"
    name_plural = "Типы документов"
    column_list = [DocumentType.id, DocumentType.code, DocumentType.name, DocumentType.description]


class EnvironmentAdmin(ModelView, model=Environment):
    name = "Окружение"
    name_plural = "Окружения"
    column_list = [Environment.id, Environment.code, Environment.name]


class FundAdmin(ModelView, model=Fund):
    name = "Фонд"
    name_plural = "Фонды"
    column_list = [Fund.id, Fund.code, Fund.name]


class CategoryAdmin(ModelView, model=Category):
    name = "Категория"
    name_plural = "Категории"
    column_list = [Category.id, Category.code, Category.name, Category.level, Category.is_active]


class SourceAdmin(ModelView, model=Source):
    name = "Источник (RSS/URL)"
    name_plural = "Источники"
    column_list = [Source.id, Source.user_id, Source.name, Source.url, Source.is_active]


class DocumentAdmin(ModelView, model=Document):
    name = "Документ"
    name_plural = "Документы"
    icon = "fa-solid fa-file-lines"
    column_list = [
        Document.id,
        Document.title,
        Document.source_url,
        Document.version,
        Document.locked_by_id,
        Document.created_at,
    ]
    column_searchable_list = [Document.title, Document.source_url]
    column_sortable_list = [Document.created_at, Document.version]


class DocumentCategoryAdmin(ModelView, model=DocumentCategory):
    name = "Категория документа"
    name_plural = "Категории документов"
    column_list = [
        DocumentCategory.document_id,
        DocumentCategory.category_id,
        DocumentCategory.confidence,
        DocumentCategory.prediction_source_id,
    ]


class TagAdmin(ModelView, model=Tag):
    name = "Тег"
    name_plural = "Теги"
    column_list = [Tag.id, Tag.name, Tag.language_id]


class DocumentTagAdmin(ModelView, model=DocumentTag):
    name = "Тег документа"
    name_plural = "Теги документов"
    column_list = [DocumentTag.document_id, DocumentTag.tag_id, DocumentTag.prediction_source_id]


class EntityTypeAdmin(ModelView, model=EntityType):
    name = "Тип сущности"
    name_plural = "Типы сущностей"
    column_list = [EntityType.id, EntityType.code, EntityType.name]


class EntityAdmin(ModelView, model=Entity):
    name = "Сущность"
    name_plural = "Сущности"
    column_list = [Entity.id, Entity.name, Entity.entity_type_id, Entity.language_id]


class DocumentEntityAdmin(ModelView, model=DocumentEntity):
    name = "Сущность документа"
    name_plural = "Сущности документов"
    column_list = [
        DocumentEntity.document_id,
        DocumentEntity.entity_id,
        DocumentEntity.prediction_source_id,
    ]


class DocumentChunkAdmin(ModelView, model=DocumentChunk):
    name = "Фрагмент (чанк)"
    name_plural = "Фрагменты"
    column_list = [
        DocumentChunk.id,
        DocumentChunk.document_id,
        DocumentChunk.chunk_type,
        DocumentChunk.chunk_index,
    ]


class EmbeddingModelAdmin(ModelView, model=EmbeddingModel):
    name = "Модель эмбеддингов"
    name_plural = "Модели эмбеддингов"
    column_list = [EmbeddingModel.id, EmbeddingModel.name, EmbeddingModel.dimension]


class DocumentEmbeddingAdmin(ModelView, model=DocumentEmbedding):
    name = "Эмбеддинг"
    name_plural = "Эмбеддинги"
    column_list = [DocumentEmbedding.id, DocumentEmbedding.chunk_id, DocumentEmbedding.embedding_model_id]
    form_columns = [DocumentEmbedding.chunk_id, DocumentEmbedding.embedding_model_id]
    can_create = False


class ProcessingJobAdmin(ModelView, model=ProcessingJob):
    name = "Задача обработки"
    name_plural = "Задачи обработки"
    column_list = [
        ProcessingJob.id,
        ProcessingJob.document_id,
        ProcessingJob.job_type,
        ProcessingJob.status,
        ProcessingJob.duration_ms,
        ProcessingJob.created_at,
    ]
    column_sortable_list = [ProcessingJob.created_at]
