FROM cgr.dev/chainguard/wolfi-base@sha256:88a20e2d017bd20cdc0cb3910de603e7bea9512a6c351a8dd3c9df212ab03d73

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:/usr/bin:/bin"
WORKDIR /app
COPY requirements-linux-py312.lock /app/requirements.lock
RUN apk add --no-cache python-3.12=3.12.16-r1 libstdc++=16.2.0-r2 tesseract=5.5.2-r8 tesseract-eng=5.5.2-r8 \
    && python3.12 -m venv /opt/venv \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.2 \
    && pip install --no-cache-dir --require-hashes --only-binary=:all: -r /app/requirements.lock \
    && python -m pip uninstall --yes pip
RUN addgroup -g 10001 pdfworker && adduser -D -u 10001 -G pdfworker pdfworker \
    && apk del wolfi-base apk-tools busybox
# Official Greek OCR data, pinned by commit and SHA-256 (not a moving download).
ADD --chmod=0644 --checksum=sha256:4fba8a0b461038d51f1c20d043d4f2ac38c4e778f1b90830847f7bd8fa3ba726 https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/923915d4ced2a7235221788285785a29c4a42d4a/ell.traineddata /usr/share/tessdata/ell.traineddata
COPY app.py /app/app.py
COPY pdf_task.py /app/pdf_task.py
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
