# ──────────── STAGE 1: builder ────────────
FROM python:3.13-slim AS builder
LABEL authors="powersemmi@gmail.com"

# Disable pip cache and install necessary tools
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PDM_VERSION=2.24.2 \
    PIP_VERSION=25.1.1 \
    SETUPTOOLS_VERSION=80.9.0 \
    WHEEL_VERSION=0.45.1 \
    PATH="/opt/app/.local/bin:$PATH" \
    PYTHONUSERBASE=/opt/app/.local

WORKDIR /opt/app

# Install pip, setuptools, wheel, then pdm and uv
RUN pip install --upgrade \
        "pip==$PIP_VERSION" \
        "setuptools==$SETUPTOOLS_VERSION" \
        "wheel==$WHEEL_VERSION" && \
    pip install --no-cache-dir \
        "pdm==$PDM_VERSION"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project metadata
COPY pyproject.toml pdm.lock /opt/app/

# Create virtual environment manually and prepare it for building
RUN python -m venv .venv \
    && . .venv/bin/activate \
    && pip install --upgrade \
        "pip==$PIP_VERSION" \
        "setuptools==$SETUPTOOLS_VERSION" \
        "wheel==$WHEEL_VERSION"

# Configure PDM to use uv as resolver/installer
RUN pdm config venv.location ".venv" \
    && pdm config use_uv true

# Setup prod dependency
RUN pdm install -v --prod --frozen-lockfile --no-editable

# ──────────── STAGE 2: tester ────────────
FROM builder AS tester

# Setup dev dependency
RUN pdm install --dev --frozen-lockfile --no-editable

# By default, run REPL for testing
ENTRYPOINT ["pdm", "run", "python"]


# ──────────── STAGE 3: runner ────────────
FROM python:3.13-slim AS runner
LABEL maintainer="powersemmi@gmail.com"

ENV TZ=Europe/Chisinau \
    PYTHONFAULTHANDLER=1 \
    PYTHONBUFFERED=1 \
    # Add .venv to PATH to immediately see installed packages
    PATH=/opt/app/.venv/bin:$PATH

WORKDIR /opt/app

# Copy application code

COPY src/crawler/migrations/alembic.ini alembic.ini
COPY src/crawler chat_parser
COPY pyproject.toml .

# Copy virtual environment from builder
COPY --from=builder /opt/app/.venv /opt/app/.venv

ENTRYPOINT ["python", "-m", "faststream", "run", "chat_parser.app:app", "--host", "0.0.0.0", "--port", "8080"]
