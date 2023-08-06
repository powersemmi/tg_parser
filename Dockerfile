FROM python:3.11-slim as builder
LABEL authors="moloko"

ENV PIP_NO_CACHE_DIR=OFF \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONPATH=/opt/app \
    PDM_VERSION=2.8.* \
    PIP_VERSION=23.1.*

WORKDIR /opt/app

RUN pip install --no-cache-dir "pdm==$PDM_VERSION" "pip==$PIP_VERSION" && \
    pdm config venv.in_project false && \
    pdm config check_update false && \
    pdm config python.use_venv false

COPY pyproject.toml pdm.lock README.md /opt/app/

RUN mkdir __pypackages__ && pdm install -v --prod --no-lock --no-editable


FROM python:3.11-slim as runner

ENV PYTHONPATH=/opt/app/pkgs \
    PYTHONFAULTHANDLER=1 \
    PYTHONBUFFERED=1

COPY --from=builder /opt/app/__pypackages__/3.10/lib /opt/app/pkgs

WORKDIR /opt/app
COPY . .

CMD ["python", "-m", "app"]

ENTRYPOINT ["python", "-m", "src"]
