# AI Tools Service

HTTP API для LLM-задач (саммари, перевод, теги и т.д.) с PostgreSQL и веб-админкой (SQLAdmin).

Ниже — **пошаговый запуск**. Конкретные имена сервисов, порты и учётные данные **не зашиты в документ**: их нужно взять из файлов репозитория (`docker-compose.yml`, `.env`).

---

## Что понадобится

- Docker и Docker Compose v2
- Файл окружения (см. раздел «Конфигурация»)

---

## 0. Обозначения

В командах ниже:

| Обозначение | Откуда взять |
|-------------|----------------|
| **`<compose-file>`** | Обычно `docker-compose.yml` в корне репозитория; при необходимости укажите `-f …`. |
| **`<app-service>`** | Ключ сервиса **приложения** в `services:` (тот, у которого `build:` / ваш API), не контейнер Postgres. |
| **`<host-app-port>`** | Порт на хосте в секции `ports:` у **`<app-service>`** (левое число в записи `HOST:CONTAINER`). |
| **`<admin-url>`** | `http://127.0.0.1:<host-app-port>/admin` (или ваш хост/прокси). |

Подставляйте свои значения вместо угловых скобок.

---

## Пример для этого репозитория

Ниже — опора на **текущий** [`docker-compose.yml`](docker-compose.yml). Если вы меняете имена сервисов, `container_name`, порты или пароль Postgres, сверяйтесь с compose и `.env`, этот блок может устареть частично.

| Что | Как сейчас в шаблоне |
|-----|----------------------|
| Внешняя сеть | `ai_stack` |
| **`<app-service>`** | `ai-tools` |
| **`<host-app-port>`** | `8010` (внутри контейнера приложения API на `8000`) |
| Сервис Postgres в compose | `postgres` |
| Хост БД **из контейнера приложения** | `ai-tools-postgres` (`container_name` Postgres) |
| `POSTGRES_DB` / `POSTGRES_USER` | `aitools` / `aitools` |
| Пароль БД | Только в compose: `services.postgres.environment.POSTGRES_PASSWORD` — тот же пароль укажите в `DATABASE_URL` в `.env`. |

**Фрагмент `.env` для API в Docker** (подставьте пароль из compose вместо плейсхолдера):

```env
DATABASE_URL=postgresql+asyncpg://aitools:ПАРОЛЬ_ИЗ_COMPOSE@ai-tools-postgres:5432/aitools
```

Остальное обязательное — по [`.env.example`](.env.example) (`OPENAI_COMPAT_*`, `JWT_SECRET_KEY` и т.д.).

**Команды** (из корня репозитория, где лежит `docker-compose.yml`):

```bash
docker network create ai_stack
docker compose up -d --build
docker compose exec ai-tools uv run python -m app.cli.init_db
```

Регистрация первого пользователя и выдача прав админа SQLAdmin:

```bash
curl -sS -X POST "http://127.0.0.1:8010/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change_me_please_8","email":"admin@example.com"}'

docker compose exec ai-tools uv run python -m app.cli.promote_admin admin
```

Админка: **http://127.0.0.1:8010/admin** — вход тем же логином и паролем, что при регистрации.

С хоста, если в `.env` для Docker указан `ai-tools-postgres`, а CLI нужно гонять локально — см. **`DATABASE_URL_FOR_CLI`** в [`.env.example`](.env.example) (URL на `127.0.0.1:5432` с тем же пользователем, БД и паролем).

---

## 1. Сеть Docker (если нужна)

Если в `docker-compose.yml` у сети указано `external: true`, сеть нужно создать **один раз** до `compose up`:

```bash
docker network create <имя-сети-из-compose>
```

Имя смотрите в том же файле в блоке `networks:`.

---

## 2. Окружение

1. Скопируйте шаблон переменных (в репозитории он обычно называется `.env.example`) в `.env`.
2. Заполните обязательные переменные. Полный перечень и смысл полей — в **`.env.example`** и в `app/core/config.py` (имена в `UPPER_SNAKE` совпадают с переменными окружения).

Минимум для поднятия стека обычно включает:

- URL и ключ OpenAI-совместимого API;
- **`DATABASE_URL`** — async-строка для SQLAlchemy (`postgresql+asyncpg://…`). Хост и порт должны быть **доступны из контейнера приложения** (часто это имя сервиса Postgres из compose, а не `127.0.0.1`);
- **`JWT_SECRET_KEY`** — секрет для выдачи токенов; не коммить в репозиторий.

Учётные данные Postgres в `DATABASE_URL` должны **совпадать** с тем, что задано для образа БД в compose (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` или эквивалент).

---

## 3. Запуск Compose

Из корня репозитория (где лежит compose-файл):

```bash
docker compose -f <compose-file> up -d --build
```

Дождитесь готовности Postgres (первый старт может занять несколько секунд).

Проверка, что API отвечает (подставьте свой порт):

```bash
curl -sS "http://127.0.0.1:<host-app-port>/docs" -o /dev/null -w "%{http_code}\n"
```

Ожидаемо `200` (или ваша политика маршрутизации для `/docs`).

---

## 4. Инициализация схемы БД

Схема накатывается **только через Alembic** (миграции). Удобная обёртка из репозитория:

```bash
docker compose -f <compose-file> exec <app-service> uv run python -m app.cli.init_db
```

Это эквивалентно `alembic upgrade head` из корня проекта внутри контейнера.

**Если CLI запускаете с хоста**, а в `.env` в `DATABASE_URL` указан docker-only hostname, используйте отдельный URL на `127.0.0.1` (в проекте для этого предусмотрена переменная **`DATABASE_URL_FOR_CLI`** — см. комментарии в `.env.example` и `app/cli/init_db.py`).

---

## 5. Первый пользователь и доступ к админке

SQLAdmin (`/admin`) доступен пользователям с флагом администратора в БД. Типовой порядок:

### 5.1. Регистрация пользователя через API

Запрос (подставьте порт и тело):

```bash
curl -sS -X POST "http://127.0.0.1:<host-app-port>/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"your_admin_login","password":"your_secure_password","email":"you@example.com"}'
```

Требования к `username` / `password` задаются схемой `UserCreate` в коде (`app/schemas/auth.py`).

### 5.2. Назначить роль администратора

```bash
docker compose -f <compose-file> exec <app-service> \
  uv run python -m app.cli.promote_admin your_admin_login
```

Имя пользователя — то же, что при регистрации (в БД оно нормализуется в нижний регистр).

### 5.3. Вход в админку

Откройте **`<admin-url>`** в браузере и войдите **под этим же пользователем** (логин / пароль регистрации). Секрет сессии админки настраивается через **`ADMIN_SESSION_SECRET`** или, если не задан, используется **`JWT_SECRET_KEY`** (см. `app/core/config.py`).

---

## 6. Локальный запуск без Docker (кратко)

Если приложение запускается на хосте, а Postgres в контейнере или локально:

1. Установите зависимости так, как принято в проекте (в репозитории используется **`uv`**).
2. Настройте `.env` так, чтобы `DATABASE_URL` указывал на доступный с хоста адрес БД.
3. Выполните `uv run python -m app.cli.init_db`.
4. Запуск сервера — см. `pyproject.toml` / скрипты проекта (точка входа может отличаться).

---

## 7. Где смотреть детали

| Вопрос | Где смотреть |
|--------|----------------|
| Переменные окружения | `.env.example`, `app/core/config.py` |
| Имена сервисов, порты, тома | `docker-compose.yml` |
| Миграции | каталог `alembic/`, `alembic.ini` |
| CLI: БД и админ | `app/cli/init_db.py`, `app/cli/promote_admin.py` |

При смене имён сервисов или портов достаточно обновить compose и `.env` — этот README менять не требуется.
