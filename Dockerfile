FROM python:3.11-slim as builder
LABEL authors="powersemmi@gmail.com"

ENV PIP_NO_CACHE_DIR=OFF \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONPATH=/opt/app \
    PDM_VERSION=2.13.* \
    PIP_VERSION=23.3.*

WORKDIR /opt/app

RUN pip install --no-cache-dir "pdm==$PDM_VERSION" "pip==$PIP_VERSION" && \
    pdm config venv.in_project false && \
    pdm config check_update false && \
    pdm config python.use_venv false

COPY pyproject.toml pdm.lock README.md /opt/app/

# Setup prod dependency
RUN mkdir __pypackages__ && pdm install -v --prod --no-lock --no-editable

FROM builder as tester

ENV PYTHONPATH=/opt/app/__pypackages__/3.11/lib
ENV PATH=$PATH:/opt/app/__pypackages__/3.11/bin

# Setup dev dependency
RUN pdm install --dev --no-lock --no-editable

CMD ["python"]

FROM python:3.11-slim as runner

ENV PYTHONPATH=/opt/app/pkgs \
    PYTHONFAULTHANDLER=1 \
    PYTHONBUFFERED=1

COPY --from=builder /opt/app/__pypackages__/3.11/lib /opt/app/pkgs

WORKDIR /opt/app
COPY src/chat_parser/migrations/alembic.ini alembic.ini
COPY src/chat_parser tg_chat_parser

ENTRYPOINT ["python", "-m", "faststream", "run", "chat_parser.app:app"]
