# Happy Ice Cream

Демо-проект розыгрыша промокодов: лендинг, личный кабинет, ежедневный розыгрыш через Celery.

## Стек

- Django 6 + Django REST Framework
- PostgreSQL
- Redis + Celery (worker + beat)
- Docker Compose

## Быстрый старт (Docker)

```bash
cp .env.example .env
docker compose up --build
```

Или через Make:

```bash
make up
```

Приложение: http://localhost:8000  
Админка: http://localhost:8000/admin/

Миграции при старте `web` применяются автоматически. Создать суперпользователя:

```bash
make createsuperuser
```

Остановить:

```bash
make down
```

## Локально без Docker-приложения

Нужны Python 3.13+, PostgreSQL и Redis (или только Redis + SQLite без `POSTGRES_HOST`).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# для SQLite уберите POSTGRES_HOST из .env
python src/manage.py migrate
python src/manage.py runserver
```

Celery:

```bash
# Redis должен быть доступен
celery -A config worker -l info
celery -A config beat -l info
```

Рабочая директория для Celery и `manage.py` — `src/`.

## Сервисы Compose

| Сервис  | Назначение                          |
|---------|-------------------------------------|
| `web`   | Gunicorn (Django), порт 8000        |
| `db`    | PostgreSQL 16                       |
| `redis` | брокер/бэкенд Celery                |
| `celery`| worker                              |
| `beat`  | расписание (розыгрыш в 12:00 UTC)   |

## Переменные окружения

Скопируйте `.env.example` → `.env` и правьте там. Compose и Django читают этот файл.

Для Docker оставьте `POSTGRES_HOST=db` и Redis-URL на `redis://redis:...`.
Локально без Compose замените хосты на `localhost`.

## Лицензия

MIT
