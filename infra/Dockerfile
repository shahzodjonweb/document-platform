FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr libreoffice-writer libreoffice-impress fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.lock \
    && useradd --create-home --uid 10001 pdfmaster
COPY --chown=pdfmaster:pdfmaster . .
RUN mkdir -p /data/private /data/static && chown -R pdfmaster:pdfmaster /data /app
USER pdfmaster
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-"]
