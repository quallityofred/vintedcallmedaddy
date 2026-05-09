# README.md
# Vinted Monitor

Система мониторинга новых товаров на маркетплейсе Vinted с веб-интерфейсом и Telegram-уведомлениями.

## Возможности

- Добавление ссылок на каталог Vinted и автоматический парсинг параметров
- Проверка товаров на основных доменах Vinted (.fr, .de, .co.uk, .it, .es, .pl, .com)
- Фильтрация promoted/showcase товаров (рекламные вставки)
- Уведомления в Telegram с фото, ценой, ссылкой на товар
- Веб-интерфейс на FastAPI + Jinja2 + HTMX + Tailwind CSS
- Умный adaptive scheduling (пиковые часы / ночной режим / быстрая адаптация)
- Кэширование сессий с переиспользованием OAuth токенов и cookies
- Автоматический fallback на Cloudflare Workers при блокировках (429/403)
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
DATABASE_URL=sqlite+aiosqlite:///./data/vinted.db
PROXIES=
SESSIONS_PER_DOMAIN=3
RATE_LIMIT_PER_MINUTE=8
```

- `TELEGRAM_BOT_TOKEN` — токен бота, полученный от [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — ID чата, куда будут приходить уведомления
- `PROXIES` — список прокси через запятую (опционально)

### 2. Локальный запуск без Docker

Установите зависимости и запустите приложение напрямую:

```bash
poetry install
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080
```

База SQLite будет создана локально в `./data/vinted.db`.

### 3. Запуск через Docker (опционально)

```bash
docker-compose up --build
```

### 4. Открыть веб-интерфейс

Перейдите по адресу [http://localhost:8080](http://localhost:8080).

### 5. Проверить настройки

Зайдите в раздел **Настройки**, проверьте что Telegram токен и Chat ID указаны верно.

### 6. Подключить Telegram бота

Отправьте команду `/start` вашему боту в Telegram. Chat ID сохранится в базе данных автоматически, а активный Telegram-бот будет подниматься после перезапуска приложения без повторного ввода токена.

### 7. Добавить первый монитор

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
│   │   ├── notifications.py # Отправка уведомлений
│   │   └── settings_store.py # Персистентное хранение активного бота в БД
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

## Защита от блокировок

### Adaptive Scheduling

Бот автоматически регулирует интервалы проверки в зависимости от времени суток:

| Период | Часы (UTC) | Множитель | Интервал (при базе 120с) |
|--------|-----------|-----------|--------------------------|
| Пиковые часы | 08:00–23:00 | 1× | 120с |
| Вечер/утро | 23:00–08:00 | 2.5× | 300с |
| Ночь | 00:00–08:00 | 5× | 600с |

При пустых проверках интервал плавно увеличивается (×1.3 после 5 пустых в пиковые часы, после 15 в остальное время). При нахождении товаров — быстро уменьшается (×0.7) до базового значения.

Настройки в `.env`:
```env
PEAK_START_HOUR=8
PEAK_END_HOUR=23
OFFPEAK_INTERVAL_MULTIPLIER=2.5
NIGHT_INTERVAL_MULTIPLIER=5.0
```

### Кэширование сессий

OAuth токены и cookies переиспользуются между запросами. Сессии возвращаются в пул после использования и хранятся до истечения (TTL) или лимита запросов (40–80 на сессию). Это снижает число "подозрительных" запросов авторизации.

### Cloudflare Workers Fallback

При получении блокировок (429/403) бот автоматически переключается на проксирование через Cloudflare Workers. Когда блокировки спадают (через `CF_WORKER_RECOVERY_MINUTES`), бот возвращается на прямой IP.

Настройки в `.env`:
```env
CF_WORKER_URL=https://your-worker.workers.dev
CF_WORKER_BLOCK_THRESHOLD=2
CF_WORKER_RECOVERY_MINUTES=10
```

Пример Cloudflare Worker для проксирования:
```javascript
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const targetUrl = url.searchParams.get("url");
    if (!targetUrl) return new Response("Missing url param", { status: 400 });
    const resp = await fetch(targetUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
      },
    });
    return new Response(resp.body, { status: resp.status, headers: resp.headers });
  },
};
```

## Технологии

- **Backend**: Python 3.11+, FastAPI, asyncio
- **База данных**: SQLite (aiosqlite) + SQLAlchemy 2.0 async
- **Парсинг**: curl_cffi (TLS fingerprint impersonation)
- **Планировщик**: APScheduler (AsyncIOScheduler)
- **Telegram**: aiogram 3.x, настройки бота и Chat ID персистятся в SQLite
- **Фронтенд**: Jinja2 + HTMX + Tailwind CSS
- **Деплой**: локальный запуск Python/Poetry или Docker
