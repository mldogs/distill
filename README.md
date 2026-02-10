# Distill

**Лучшее из Telegram** — система агрегации и ранжирования контента из публичных Telegram-каналов с AI-скорингом, LLM-анализом уникальности и автоматической фильтрацией спама.

## Что делает Distill

Distill собирает посты из публичных Telegram-каналов, оценивает их по нескольким формулам ранжирования и показывает лучший контент через веб-интерфейс. Система включает голосование, LLM-анализ уникальности контента (novelty/essence) и автоматические pipeline обновлений.

---

## Содержание

- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Требования](#требования)
- [Установка](#установка)
- [Запуск через Docker](#запуск-через-docker)
- [Запуск без Docker](#запуск-без-docker)
- [Переменные окружения](#переменные-окружения)
- [API](#api)
- [Веб-интерфейс](#веб-интерфейс)
- [Админ-панель](#админ-панель)
- [Формулы ранжирования](#формулы-ранжирования)
- [Автоматизация (Jobs)](#автоматизация-jobs)
- [Деплой на VPS](#деплой-на-vps)
- [Тесты](#тесты)
- [Стек технологий](#стек-технологий)

---

## Возможности

### Многоуровневое ранжирование (Stills)
- **refined (v2)** — нормализация относительно канала (маленькие каналы не проигрывают большим)
- **essence (v3)** — v2 + LLM-анализ уникальности контента
- **triple (v4)** — тройная дистилляция: v3 + штраф за спам-частоту публикаций

### LLM-анализ уникальности (Essence)
- 10 критериев оценки: эксклюзивность, уникальность, глубина, перспектива, фактологичность, данные, источники, контекст, практичность, ясность
- Настраиваемые веса для каждого критерия (через API настроек)
- Сравнение с недавними постами для выявления информационного прироста

### Антиспам-фильтр (Purity)
- Штраф каналам с чрезмерной частотой публикации
- Настраиваемые пороги

### Веб-интерфейс
- Лента постов с периодами (24ч / 7д / 30д / всё время)
- Топ-10 + вкладка «Бездна» для постов за пределами топа
- Переключение между формулами (v2, v3, v4)
- Объяснение скора с разбивкой по фичам
- Полнотекстовый и семантический поиск
- Голосование за посты
- Админ-панель для управления каналами и настройками

### Автоматический pipeline
- Периодический сбор постов из каналов
- Автоматический пересчёт ранжирования
- Запланированный LLM-анализ новых постов
- Генерация эмбеддингов для семантического поиска

---

## Архитектура

```
collector/   → Сбор данных из Telegram (Telethon)
storage/     → Модели PostgreSQL, миграции (async SQLAlchemy + Alembic)
ranker/      → Формулы скоринга и извлечение фич
novelty/     → LLM-анализ уникальности контента (OpenRouter)
core/        → Менеджер настроек, профилирование задач
api/         → FastAPI REST-бэкенд
web/         → Next.js фронтенд (React + Tailwind)
jobs/        → Celery воркеры и планировщик
tests/       → Unit и интеграционные тесты
scripts/     → Утилиты (бенчмарки, миграции данных)
```

### Поток данных

```
1. Ingest:    Telegram API → Collector → PostgreSQL (upsert)
2. Score:     PostgreSQL → Ranker → Scores (upsert)
3. Novelty:   PostgreSQL → LLM (OpenRouter) → novelty_score в posts
4. Display:   API → Web (топ-посты, голосование, поиск)
```

---

## Требования

- **Python** 3.11+
- **Node.js** 18+
- **PostgreSQL** 15+ (с расширением pgvector)
- **Redis** 7+
- **Telegram API** credentials ([my.telegram.org](https://my.telegram.org))
- **OpenRouter API key** (для LLM-анализа уникальности, опционально)

---

## Установка

### 1. Клонирование и настройка

```bash
git clone <repository-url>
cd distill

# Установка зависимостей Python
pip install -r requirements.txt

# Копирование и заполнение переменных окружения
cp .env.example .env
# Отредактируйте .env — заполните TG_API_ID, TG_API_HASH, DB_PASSWORD и т.д.
```

### 2. Генерация Telegram-сессии

```bash
python collector/get_session.py
# Следуйте инструкциям — введите номер телефона и код из Telegram
# Полученную строку сессии запишите в TG_SESSION в .env
```

### 3. Настройка базы данных

```bash
cd storage && alembic upgrade head && cd ..
```

### 4. Установка фронтенда

```bash
cd web
npm install
cd ..
```

---

## Запуск через Docker

Docker — рекомендуемый способ запуска. Все сервисы описаны в `docker-compose.yml`.

### Запуск всех сервисов

```bash
docker-compose up -d --build
```

### Только инфраструктура (PostgreSQL + Redis)

```bash
docker-compose up -d postgres redis
```

### С мониторингом (Flower + Umami)

```bash
docker-compose --profile monitoring up -d
```

### Применение миграций

```bash
docker exec tg-exchange-api alembic -c /app/storage/alembic.ini upgrade head
```

### Просмотр логов

```bash
docker-compose logs -f api           # API
docker-compose logs -f celery-worker # Воркер
docker-compose logs -f web           # Фронтенд
```

### Остановка

```bash
docker-compose down       # сохранить данные
docker-compose down -v    # удалить volumes (чистый старт)
```

### Сервисы и порты

| Сервис | Порт | Описание |
|--------|------|----------|
| `postgres` | 5432 | PostgreSQL 15 + pgvector |
| `redis` | 6379 | Redis 7 (брокер + кэш) |
| `api` | 8000 | FastAPI бэкенд |
| `web` | 3000 | Next.js фронтенд |
| `celery-worker` | — | Обработчик задач |
| `celery-beat` | — | Планировщик задач |
| `flower` | 5555 | Мониторинг Celery (опционально) |
| `umami` | 3001 | Веб-аналитика (опционально) |

---

## Запуск без Docker

### Бэкенд (API)

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Фронтенд

```bash
cd web && npm run dev
```

### Celery воркер + планировщик

```bash
# В отдельных терминалах:
celery -A jobs.celery_app worker -l info
celery -A jobs.celery_app beat -l info
```

### Сбор постов (CLI)

```bash
# Из конфига каналов
python collector/fetch.py --config collector/channels.yaml --out-dir collector/data

# Конкретный канал
python collector/fetch.py --channel @durov --limit 100
```

### Ранжирование (CLI)

```bash
# За последние 24 часа формулой v4
python -m ranker.cli --formula v4 --period 24h

# Недельный рейтинг с сохранением
python -m ranker.cli --formula v3 --period weekly --save

# Произвольный диапазон дат
python -m ranker.cli --formula v2 --since 2026-01-01 --until 2026-01-10
```

---

## Переменные окружения

Все переменные хранятся в `.env` (см. `.env.example`).

### Обязательные

| Переменная | Описание |
|------------|----------|
| `TG_API_ID` | API ID из [my.telegram.org](https://my.telegram.org) |
| `TG_API_HASH` | API Hash из [my.telegram.org](https://my.telegram.org) |
| `TG_SESSION` | Строка сессии (генерируется через `python collector/get_session.py`) |
| `DB_PASSWORD` | Пароль PostgreSQL |
| `TELEGRAM_BOT_TOKEN` | Токен бота для Telegram Login Widget |
| `ADMIN_IDS` | Telegram user ID администратора (или несколько через запятую) |
| `NEXT_PUBLIC_API_URL` | URL API для фронтенда (например `https://yourdomain.com`) |
| `NEXT_PUBLIC_TELEGRAM_BOT_NAME` | Username бота (без @) для виджета авторизации |

### Опциональные

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `DB_HOST` | Хост БД | `localhost` |
| `DB_PORT` | Порт БД | `5432` |
| `DB_NAME` | Имя БД | `telegram_exchange` |
| `DB_USER` | Пользователь БД | `postgres` |
| `REDIS_URL` | URL Redis | `redis://localhost:6379/0` |
| `TELEGRAM_RATE_LIMIT` | Лимит запросов к Telegram API | `20/s` |
| `OPENROUTER_API_KEY` | Ключ OpenRouter (для novelty и семантического поиска) | — |
| `NOVELTY_WEIGHT` | Вес novelty в v3/v4 (3=баланс, 5=норма, 7-10=novelty) | `5` |
| `AVG_POSTS_PER_DAY` | Базовая частота для антиспам-штрафа в v4 | `5` |
| `JWT_SECRET` | Секрет для JWT-токенов | автогенерация |
| `CORS_ORIGINS` | Разрешённые origin (через запятую или `*`) | `http://localhost:3000` |

### Минимальный .env для production

```bash
TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1
TG_SESSION=<строка_из_get_session.py>

DB_HOST=localhost
DB_PORT=5432
DB_NAME=telegram_exchange
DB_USER=postgres
DB_PASSWORD=your_secure_password

REDIS_URL=redis://localhost:6379/0
TELEGRAM_RATE_LIMIT=20/s

TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx
ADMIN_IDS=123456789
CORS_ORIGINS=*

NEXT_PUBLIC_API_URL=https://yourdomain.com
NEXT_PUBLIC_TELEGRAM_BOT_NAME=your_bot_name

OPENROUTER_API_KEY=sk-or-v1-...

NOVELTY_WEIGHT=5
AVG_POSTS_PER_DAY=5
```

---

## API

Swagger-документация доступна по адресу `http://localhost:8000/docs` при запущенном сервере.

### Публичные эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/health` | Проверка работоспособности |
| `GET` | `/feed` | Лента постов (ранжированных) |
| `GET` | `/search` | Поиск (полнотекстовый + семантический) |
| `GET` | `/stats` | Статистика системы |
| `GET` | `/summary` | Последний саммари |
| `POST` | `/vote` | Голосование за пост (требует JWT) |
| `POST` | `/auth/telegram` | Авторизация через Telegram |
| `POST` | `/auth/dev-login` | Dev-логин (только при `ENABLE_DEV_LOGIN=true`) |
| `GET` | `/auth/me` | Текущий пользователь |

### Параметры `/feed`

| Параметр | Значения | По умолчанию | Описание |
|----------|----------|--------------|----------|
| `period` | `24h`/`daily`, `7d`/`weekly`, `30d`/`monthly`, `all` | `weekly` | Период |
| `limit` | 1–100 | 50 | Количество постов |
| `offset` | 0+ | 0 | Смещение для пагинации |
| `formula` | `v2`, `v3`, `v4` | `v4` | Формула ранжирования |
| `channel` | `@username` | — | Фильтр по каналу |
| `sort_by` | `score`, `posted_at`, `views`, `replies`, `reactions`, `forwards`, `novelty` | `score` | Сортировка |
| `sort_dir` | `asc`, `desc` | `desc` | Направление сортировки |
| `min_views` | число | — | Мин. просмотры |
| `min_replies` | число | — | Мин. ответы |
| `min_reactions` | число | — | Мин. реакции |
| `min_forwards` | число | — | Мин. репосты |
| `min_novelty` | 0.0–1.0 | — | Мин. novelty score |

### Параметры `/search`

| Параметр | Значения | По умолчанию | Описание |
|----------|----------|--------------|----------|
| `q` | строка (1–500 символов) | — (обязательный) | Поисковый запрос |
| `mode` | `lexical`, `semantic`, `hybrid` | `hybrid` | Режим поиска |
| `limit` | 1–100 | 20 | Количество результатов |
| `offset` | 0+ | 0 | Смещение для пагинации |
| `channel` | `@username` | — | Фильтр по каналу |
| `min_views` | число | — | Мин. просмотры |
| `min_replies` | число | — | Мин. ответы |
| `min_reactions` | число | — | Мин. реакции |
| `min_forwards` | число | — | Мин. репосты |
| `since` | datetime | — | Посты после даты |
| `until` | datetime | — | Посты до даты |

> Режим `semantic` требует `OPENROUTER_API_KEY` и предварительной генерации эмбеддингов. Если API-ключ не настроен, `hybrid` автоматически откатывается к `lexical`.

### Примеры

```bash
# Топ постов за неделю (period=weekly по умолчанию)
curl "http://localhost:8000/feed?limit=10&formula=v4"

# Поиск
curl "http://localhost:8000/search?q=искусственный+интеллект&limit=20"

# Статистика
curl "http://localhost:8000/stats"

# Голосование (с авторизацией)
curl -X POST http://localhost:8000/vote \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"post_id": 123, "value": 1}'
```

---

## Веб-интерфейс

### Главная страница (`/`)

Основная лента с ранжированными постами:

- **Поиск** — полнотекстовый поиск по постам (горячая клавиша `/`)
- **Периоды** — переключение между 24ч / 7д / 30д / всё время
- **Режимы просмотра**:
  - *Топ-10* — лучшие посты по выбранной формуле
  - *Бездна* — все остальные посты с пагинацией
- **Фильтры** — минимальные значения по просмотрам, реакциям, ответам, репостам, novelty
- **Сортировка** — по скору, дате, просмотрам, реакциям и другим метрикам
- **Карточки постов** — текст, канал, дата, метрики, Proof (скор), объяснение скоринга
- **Голосование** — кнопки up/down для авторизованных пользователей
- **Статистика** — количество каналов, постов, трендовые метрики

### Страница админа (`/admin`)

Доступна только авторизованным администраторам (см. `ADMIN_IDS` в `.env`).

---

## Админ-панель

Админ-панель выполнена в стиле терминала и предоставляет полный контроль над системой.

### Управление каналами

#### Выбор цели (Target)
- **single** — работа с одним каналом (`@username`)
- **selected** — выбор нескольких каналов из списка активных (с поиском)
- **all active** — все активные каналы в системе

#### Добавление каналов
- **Одиночное добавление** — через поле ввода username
- **Массовый импорт (bulk)** — вставка списка каналов (по одному на строку) или загрузка `.txt` файла
- Опция `auto_rank` — автоматически запустить ранжирование после импорта

#### Список каналов (channels)
- Показывает все каналы: username, название, статус (active/inactive), количество постов
- **Переключение статуса** — active/inactive (неактивные каналы не участвуют в сборе и ранжировании)
- **Удаление** — удаляет канал и все его посты (необратимо)

### Сбор постов (Ingestion)

Кнопка **sync** запускает сбор постов для выбранной цели.

#### Режимы сбора (mode)
| Режим | Описание | Когда использовать |
|-------|----------|--------------------|
| `window` | Загрузка последних N дней | Первоначальная загрузка, бэкфилл |
| `incremental` | Только новые посты с последнего сбора | Регулярные обновления (автоматика) |
| `refresh_recent` | Перезагрузка недавних постов | Обновление метрик (просмотры, реакции) |

#### Параметры
- **days** — глубина окна для режима `window` (1, 3, 7, 14, 30 дней)
- **limit** — максимум сообщений на канал (опционально)
- **Grace period** — буфер для incremental-режима (настраивается в Settings)
- **Refresh window** — окно для refresh_recent (настраивается в Settings)

### Ранжирование (Ranking)

Кнопка **rank** запускает скоринг постов.

- **Период** — daily (1д), weekly (7д), monthly (30д)
- **Формула** — v4 (рекомендуется) или v3

### Novelty-анализ

Кнопка **novelty** запускает LLM-анализ уникальности контента. Требует `OPENROUTER_API_KEY`.

#### Параметры
| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `analysis_hours` | Окно анализа (какие посты анализировать) | 48ч |
| `context_days` | Контекст для сравнения (с чем сравнивать) | 30д |
| `force` | Пересчитать для постов с существующим скором | false |
| `allow_large_backfill` | Разрешить анализ >7 дней (дорого) | false |

Когда `force=true`, кнопка отображается как **novelty!**

### Pipeline (Полный цикл)

Кнопка **pipeline** запускает полный цикл обновления:

```
fetch → channel-stats → rank (контекстная формула) → novelty → rank (финальная формула)
```

#### Параметры pipeline
- `since_days` — глубина сбора (по умолчанию 1 день)
- `with_novelty` — включать LLM-анализ (по умолчанию да)
- `context_formula` — формула для контекста novelty (v2)
- `final_formula` — финальная формула ранжирования (v4)
- `rank_periods` — для каких периодов считать (daily, weekly, monthly)
- `fetch_mode` — режим сбора (window, incremental, refresh_recent)
- `channels` — ограничить конкретными каналами (опционально)

### Настройки (config)

Раздел **config** управляет runtime-настройками системы:

#### Общие настройки
| Ключ | Описание | Диапазон |
|------|----------|----------|
| `ranking.post_limit` | Макс. постов для ранжирования | 100–500000 |
| `ranking.novelty_weight` | Вес novelty в формулах v3/v4 | 0.0–20.0 |
| `ranking.avg_posts_per_day` | Базовая частота для v4 штрафа | 0.1–100.0 |

#### Настройки коллектора
| Ключ | Описание | Диапазон |
|------|----------|----------|
| `collector.fetch_window_days` | Окно сбора по умолчанию | 1–30 |
| `collector.deep_fetch_days` | Глубина ежедневного глубокого сбора | 1–90 |
| `collector.incremental_grace_minutes` | Буфер для incremental | 0–180 мин |
| `collector.refresh_recent_hours` | Окно для refresh_recent | 1–168 ч |

#### Настройки novelty
| Ключ | Описание | Диапазон |
|------|----------|----------|
| `novelty.context_days` | Дни контекста для LLM | 1–90 |
| `novelty.batch_limit` | Размер батча анализа | 1–500 |

#### Автоматизация
| Ключ | Описание | По умолчанию |
|------|----------|--------------|
| `automation.ingestion_incremental_enabled` | Автосбор новых постов | true |
| `automation.ingestion_incremental_minutes` | Интервал автосбора | 5 мин |
| `automation.ingestion_refresh_enabled` | Обновление метрик | true |
| `automation.ingestion_refresh_minutes` | Интервал обновления | 60 мин |
| `automation.novelty_enabled` | Авто novelty-анализ | true |
| `automation.novelty_minutes` | Интервал novelty | 5 мин |
| `automation.rank_daily_v4_enabled` | Автоматический ранкинг | true |
| `automation.rank_daily_v4_minutes` | Интервал ранкинга | 5 мин |
| `automation.embeddings_enabled` | Автогенерация эмбеддингов | true |
| `automation.embeddings_minutes` | Интервал генерации эмбеддингов | 60 мин |

#### Веса критериев Essence
Настраиваемые веса для 10 критериев LLM-анализа (шкала 0–10):
exclusivity, uniqueness, depth, perspective, factual, data, sources, context, actionable, clarity

### Профилирование (perf)

Раздел **perf** показывает статистику выполнения задач за последние 7 дней:
- Количество запусков каждой задачи
- Среднее и максимальное время выполнения
- Процент успешных запусков
- Очистка старых записей

### Эмбеддинги (Embeddings)

Управление векторными эмбеддингами для семантического поиска:
- **Backfill** — генерация эмбеддингов для постов без них
- **Status** — статистика покрытия (сколько постов имеют эмбеддинги)

### Отслеживание задач

Все операции выполняются асинхронно через Celery:
- Каждая операция возвращает `task_id`
- Статус задачи опрашивается каждые 2 секунды
- Результаты отображаются в терминальном логе
- Таймаут опроса — 30 минут

### Admin API эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| `POST` | `/admin/pipeline` | Полный pipeline (fetch → stats → rank → novelty → rank) |
| `POST` | `/admin/collect` | Сбор постов из каналов |
| `POST` | `/admin/ingest` | Добавление + сбор каналов (рекомендуется) |
| `POST` | `/admin/import` | Массовый импорт каналов |
| `POST` | `/admin/rank` | Запуск ранжирования |
| `POST` | `/admin/novelty` | Novelty-анализ (query params) |
| `POST` | `/admin/novelty/run` | Novelty-анализ (JSON body, с фильтром по каналам) |
| `POST` | `/admin/channel-stats` | Обновить статистику каналов |
| `POST` | `/admin/channel` | Добавить канал |
| `GET` | `/admin/channels` | Список каналов |
| `PATCH` | `/admin/channel/{id}` | Переключить статус канала |
| `DELETE` | `/admin/channel/{id}` | Удалить канал (необратимо) |
| `GET` | `/admin/task/{id}` | Статус Celery задачи |
| `GET` | `/admin/settings` | Все настройки |
| `PUT` | `/admin/settings` | Обновить настройки |
| `GET` | `/admin/settings/{key}` | Одна настройка |
| `POST` | `/admin/embeddings/backfill` | Генерация эмбеддингов |
| `GET` | `/admin/embeddings/status` | Покрытие эмбеддингами |
| `GET` | `/admin/profiling` | Последние запуски задач |
| `GET` | `/admin/profiling/stats` | Агрегированная статистика |
| `DELETE` | `/admin/profiling/cleanup` | Очистка старых записей |
| `GET` | `/admin/config` | Статус конфигурации (наличие ключей API) |

---

## Формулы ранжирования

Каждая формула — это «перегонный куб» (Still), через который проходит контент. Доступны три формулы: v2, v3, v4.

### refined (v2)
```
views_ratio = views / channel_avg_views
forwards_ratio = forwards / channel_avg_forwards
engagement_bonus = min(engagement_rate × 50, 10)
proof = (w1×log(1+views_ratio) + w2×log(1+forwards_ratio) + w3×engagement_bonus + w4×log(1+replies)) × freshness
```
- `freshness` — экспоненциальный (daily/weekly) или гиперболический (monthly/all) спад, с нижним порогом 0.1
- Нормализация относительно канала: маленькие каналы с качественным контентом конкурируют с крупными
- Каналы без статистики используют fallback-значения (1000 views, 10 forwards)

### essence (v3)
```
proof = refined_proof + NOVELTY_WEIGHT × novelty_score
```
К v2 добавляется LLM-оценка уникальности контента (0–1). Вес настраивается через `NOVELTY_WEIGHT`:
- 3 — сбалансированно (engagement важнее)
- 5 — по умолчанию
- 7–10 — essence доминирует

### triple (v4)
```
proof = essence_proof × purity_factor
purity_factor = 1 / (1 + log(1 + posts_per_day / AVG_POSTS_PER_DAY))
```
К v3 добавляется штраф за частоту публикации:

| Постов/день | Purity | Эффект |
|-------------|--------|--------|
| 2 | ≈ 0.85 | Лёгкий |
| 5 | ≈ 0.77 | Умеренный |
| 20 | ≈ 0.55 | Значительный |
| 50 | ≈ 0.44 | Сильный |

Каждый скор хранит `formula_version` и `explanation` — объяснение вклада каждой фичи.

---

## Автоматизация (Jobs)

Система использует **Celery + Redis** для фоновых задач.

### Фиксированные задания (Celery Beat)

| Время (UTC) | Задача |
|-------------|--------|
| 00:10 | Недельный рейтинг (v3) |
| 00:15 | Недельный рейтинг (v4) |
| 00:20 | Месячный рейтинг (v3) |
| 00:25 | Месячный рейтинг (v4) |
| 03:00 | Глубокий сбор (последние 7 дней, все каналы) |

### Динамическая автоматизация (automation_tick)

Каждую минуту выполняется `automation_tick`, который проверяет настройки из БД и запускает задачи по интервалам:

| Задача | Интервал по умолчанию | Описание |
|--------|----------------------|----------|
| Incremental ingestion | 5 мин | Сбор только новых постов |
| Refresh ingestion | 60 мин | Обновление метрик (просмотры, реакции) |
| Novelty analysis | 5 мин | LLM-анализ новых постов |
| Daily ranking (v4) | 5 мин | Пересчёт дневного рейтинга |
| Embeddings backfill | 60 мин | Генерация эмбеддингов |

Все интервалы настраиваются через `GET/PUT /admin/settings` (ключи `automation.*`).

### Жизненный цикл поста

| Время | Событие | Views | Forwards | Proof (v4) |
|-------|---------|-------|----------|------------|
| 10:00 | Пост опубликован | — | — | — |
| 10:05 | Первый fetch | 500 | 2 | 12.3 |
| 10:10 | Пост завирусился | 5000 | 50 | 18.7 |
| 10:15 | Продолжает расти | 15000 | 200 | 22.1 |
| 11:00 | Стабилизировался | 20000 | 250 | 23.4 |

Скоры **пересчитываются** каждые 5 минут на основе актуальных метрик. Novelty score вычисляется один раз (уникальность контента не меняется).

### Ручной запуск задач

```bash
# Сбор одного канала
python -c "from jobs.tasks import fetch_channel; fetch_channel.delay('@durov')"

# Сбор всех каналов
python -c "from jobs.tasks import fetch_all_channels; fetch_all_channels.delay()"

# Ранжирование
python -c "from jobs.tasks import rank_posts; rank_posts.delay('weekly')"

# Novelty-анализ
python -c "from jobs.tasks import compute_novelty_scores; compute_novelty_scores.delay(limit=100)"
```

---

## Деплой на VPS

### 1. Настройка сервера

```bash
git clone <repository-url>
cd distill
cp .env.example .env
nano .env  # Заполните переменные (см. раздел «Переменные окружения»)
```

### 2. Запуск контейнеров

```bash
docker compose up -d --build

# Миграции (если не AUTO_MIGRATE)
docker exec tg-exchange-api alembic -c /app/storage/alembic.ini upgrade head

# Проверка
docker ps
```

### 3. Настройка Nginx

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # API (FastAPI)
    location ~ ^/(health|feed|vote|auth|stats|summary|search)(/|$) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Admin API
    location ~ ^/admin/.+ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Swagger docs
    location ~ ^/(docs|redoc|openapi.json) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4. SSL

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

### 5. Добавление каналов

```bash
# Получить токен (dev-режим)
TOKEN=$(curl -s -X POST "http://localhost:8000/auth/dev-login?username=admin" | jq -r '.access_token')

# Добавить каналы
curl -X POST "http://localhost:8000/admin/ingest" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channels": ["@channel1", "@channel2"], "mode": "window", "since_days": 7}'
```

Каналы начнут автоматически обновляться каждые 5 минут.

---

## Тесты

```bash
# Все тесты
pytest tests/ -v

# С отчётом покрытия
pytest tests/ --cov=. --cov-report=html

# Конкретный модуль
pytest tests/test_api.py -v
pytest tests/test_ranker_formulas.py -v
```

---

## Стек технологий

**Бэкенд:**
- Python 3.11+, FastAPI, async SQLAlchemy, PostgreSQL 15 + pgvector
- Celery + Redis (фоновые задачи)
- Telethon (Telegram API)
- OpenRouter API (LLM для novelty-анализа)

**Фронтенд:**
- Next.js 14, React, TypeScript
- Tailwind CSS

**Инфраструктура:**
- Docker, Docker Compose
- Alembic (миграции БД)
- pytest (тестирование)
- Nginx + Let's Encrypt (production)

---

## Лицензия

MIT
