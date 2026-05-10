# Vinted Monitor Bot 🤖

Профессиональный инструмент для мониторинга товаров на Vinted с Telegram-уведомлениями и веб-дашбордом.

## Основные возможности
- **Live Monitoring**: Мониторинг множества ссылок с адаптивными интервалами.
- **Deduplication**: Атомарная дедупликация на уровне БД (защита от дублей).
- **Dashboard**: Веб-интерфейс на FastAPI с лайв-консолью и статистикой в реальном времени.
- **Cloud-Ready**: Полная поддержка облачных баз данных (Supabase PostgreSQL), SSL и Transaction Mode.

## Быстрый старт
1. Клонируй репозиторий: 
   ```bash
   git clone https://github.com/tellaboutme/vintedbot
   cd vintedbot
   ```
2. Скопируй пример конфигурации: `cp .env.example .env`
3. Установи зависимости: `poetry install`
4. Запусти приложение: `poetry run uvicorn app.main:app`

## Production
Проект оптимизирован для работы в Docker-контейнерах (поддерживает Railway, Render). Для работы с облачными БД (Supabase/Neon) требуется использование порта 6543 и SSL.

## Лицензия
MIT
