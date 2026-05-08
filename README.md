# README.md
# Vinted Monitor

Система мониторинга новых товаров на маркетплейсе Vinted с веб-интерфейсом и Telegram-уведомлениями.

## Возможности

- Добавление ссылок на каталог Vinted и автоматический парсинг параметров
- Проверка товаров на всех доменах Vinted (.fr, .de, .co.uk, .pl, .it, .es, .nl, .be, .cz, .lt, .pt, .at, .com и других)
- Фильтрация promoted/showcase товаров (рекламные вставки)
- Уведомления в Telegram с фото, ценой, ссылкой на товар
- Веб-интерфейс на FastAPI + Jinja2 + HTMX + Tailwind CSS
- Адаптивные интервалы проверки и ночной режим
- Скрытие нежелательных продавцов
- Ротация сессий через мобильный iOS API Vinted

## Быстрый старт

### 1. Настройка окружения

Скопируйте `.env.example` в `.env` и заполните переменные:

```bash
cp .env.example .env
```

Отредактируйте `.env`:
```env
TELEGRAM_BOT_TOKEN=8605884311:AAEdjC_EcB5WHOT7JpBxi_EhOQPOwjyNa7s
TELEGRAM_CHAT_ID=8631266527
CHECK_INTERVAL_SECONDS=120
DATABASE_URL=sqlite+aiosqlite:///data/vinted.db
PROXIES=
SESSIONS_PER_DOMAIN=3
RATE_LIMIT_PER_MINUTE=8
```

- `TELEGRAM_BOT_TOKEN` — токен бота, полученный от [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — ID чата, куда будут приходить уведомления
- `PROXIES` — список прокси через запятую (опционально)

### 2. Запуск через Docker

```bash
docker-compose up --build
```

### 3. Открыть веб-интерфейс

Перейдите по адресу [http://localhost:8080](http://localhost:8080).

### 4. Проверить настройки

Зайдите в раздел **Настройки**, проверьте что Telegram токен и Chat ID указаны верно.

### 5. Подключить Telegram бота

Отправьте команду `/start` вашему боту в Telegram. Chat ID сохранится автоматически.

### 6. Добавить первый монитор

1. Перейдите в раздел **Мониторы** → **Добавить**
2. Вставьте URL каталога Vinted, например:
   ```
   https://www.vinted.co.uk/catalog?order=newest_first&brand_ids[]=3994641
   ```
3. Выберите домены для проверки (по умолчанию все)
4. Укажите интервал проверки (по умолчанию 120 секунд)
5. Нажмите **Создать**

Бот начнёт присылать уведомления о новых товарах в Telegram.

## Команды Telegram бота

| Команда | Описание |
|---------|----------|
| `/start` | Подключить бота к чату |
| `/status` | Статистика: активные мониторы, товары за сегодня |
| `/list` | Список всех мониторов |
| `/pause` | Приостановить все мониторы |
| `/resume` | Возобновить все мониторы |

В уведомлениях о товарах есть кнопка **Скрыть продавца** — товары от этого продавца больше не будут приходить.

## Структура проекта

```
vinted_bot/
├── app/
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py            # Настройки (pydantic-settings)
│   ├── database.py          # Async SQLAlchemy engine + сессии
│   ├── models.py            # Модели БД (Monitor, FoundItem, ...)
│   ├── scraper/             # Парсинг Vinted API
│   │   ├── client.py        # VintedClient (поиск по доменам)
│   │   ├── session_manager.py  # Ротация OAuth сессий
│   │   ├── parser.py        # Парсинг ответа API
│   │   ├── rate_limiter.py  # Token bucket rate limiter
│   │   ├── url_parser.py    # Парсинг URL каталога
│   │   └── domains.py       # Список доменов Vinted
│   ├── scheduler/           # APScheduler задачи
│   │   └── tasks.py         # MonitorScheduler + check_monitor
│   ├── telegram/            # Telegram бот
│   │   ├── bot.py           # Создание и запуск бота
│   │   ├── handlers.py      # Обработчики команд
│   │   └── notifications.py # Отправка уведомлений
│   ├── web/                 # Веб-интерфейс
│   │   ├── router.py        # FastAPI маршруты
│   │   ├── schemas.py       # Pydantic схемы
│   │   └── dependencies.py  # Dependency injection
│   ├── templates/           # Jinja2 шаблоны
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── settings.html
│   │   ├── logs.html
│   │   └── monitors/
│   │       ├── list.html
│   │       ├── form.html
│   │       └── partials/
│   │           └── monitor_row.html
│   └── static/
│       └── css/
│           └── custom.css
├── data/                    # SQLite БД (создаётся автоматически)
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Технологии

- **Backend**: Python 3.11+, FastAPI, asyncio
- **База данных**: SQLite (aiosqlite) + SQLAlchemy 2.0 async
- **Парсинг**: curl_cffi (TLS fingerprint impersonation)
- **Планировщик**: APScheduler (AsyncIOScheduler)
- **Telegram**: aiogram 3.x
- **Фронтенд**: Jinja2 + HTMX + Tailwind CSS
- **Деплой**: Docker + docker-compose
