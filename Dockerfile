# ──────────── STAGE 1: builder ────────────
FROM python:3.13-slim AS builder
LABEL authors="powersemmi@gmail.com"

# Отключаем кеш pip и устанавливаем нужные инструменты
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PDM_VERSION=2.24.2 \
    PIP_VERSION=25.1.1 \
    SETUPTOOLS_VERSION=80.9.0 \
    WHEEL_VERSION=0.45.1 \
    PATH="/opt/app/.local/bin:$PATH" \
    PYTHONUSERBASE=/opt/app/.local

WORKDIR /opt/app

# Устанавливаем pip, setuptools, wheel, затем pdm и uv
RUN pip install --upgrade \
        "pip==$PIP_VERSION" \
        "setuptools==$SETUPTOOLS_VERSION" \
        "wheel==$WHEEL_VERSION" && \
    pip install --no-cache-dir \
        "pdm==$PDM_VERSION"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Копируем метаданные проекта
COPY pyproject.toml pdm.lock /opt/app/

# Создаём виртуальное окружение вручную и подготавливаем его для сборки
RUN python -m venv .venv \
    && . .venv/bin/activate \
    && pip install --upgrade \
        "pip==$PIP_VERSION" \
        "setuptools==$SETUPTOOLS_VERSION" \
        "wheel==$WHEEL_VERSION"

# Настраиваем PDM на использование uv как резолвера/установщика
RUN pdm config venv.location ".venv" \
    && pdm config use_uv true

# Setup prod dependency
RUN pdm install -v --prod --frozen-lockfile --no-editable

# ──────────── STAGE 2: tester ────────────
FROM builder AS tester

# Setup dev dependency
RUN pdm install --dev --frozen-lockfile --no-editable

# По умолчанию запускаем REPL для тестирования
ENTRYPOINT ["pdm", "run", "python"]


# ──────────── STAGE 3: runner ────────────
FROM python:3.13-slim AS runner
LABEL maintainer="powersemmi@gmail.com"

ENV TZ=Europe/Chisinau \
    PYTHONFAULTHANDLER=1 \
    PYTHONBUFFERED=1 \
    # Добавляем .venv в PATH, чтобы сразу видеть установленные пакеты
    PATH=/opt/app/.venv/bin:$PATH

WORKDIR /opt/app

# Копируем код приложения

COPY src/crawler/migrations/alembic.ini alembic.ini
COPY src/crawler chat_parser
COPY pyproject.toml .

# Копируем виртуальное окружение из билдера
COPY --from=builder /opt/app/.venv /opt/app/.venv

ENTRYPOINT ["python", "-m", "faststream", "run", "chat_parser.app:app", "--host", "0.0.0.0", "--port", "8080"]
