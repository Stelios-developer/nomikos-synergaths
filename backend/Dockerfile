FROM cgr.dev/chainguard/wolfi-base@sha256:24f549a7fcace88e69b9557941168c74645688ecc4acf7fb6d734a6b74e9019d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:/usr/bin:/bin"
WORKDIR /app
COPY requirements-linux-py312.lock /app/requirements.lock
RUN apk add --no-cache python-3.12=3.12.16-r1 libstdc++=16.2.0-r2 libgomp=16.2.0-r2 \
    && python3.12 -m venv /opt/venv \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2 \
    && python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock \
    && python -m pip uninstall --yes pip
RUN addgroup -g 10001 dmc && adduser -D -u 10001 -G dmc dmc \
    && mkdir -p /data/pdfs && chown -R 10001:10001 /data \
    && apk del wolfi-base apk-tools busybox
COPY db ./db
COPY services ./services
COPY routers ./routers
COPY main.py contracts.py ./
ENV PDF_STORAGE_DIR=/data/pdfs DOCUMENT_CASE_DB_PATH=/data/document_cases.db \
    EVAL_DB_PATH=/data/evaluation.db OBSERVABILITY_DB_PATH=/data/observability.db
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
