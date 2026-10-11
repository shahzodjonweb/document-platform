FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
# Document scanner weights (~126 MB), pinned by size and SHA-256 in
# models.json, in their own layer and outside /app: root-owned, read-only,
# never touched by the chown below. Runtime needs no network for them.
COPY processors/scanner/models.json /tmp/scanner/models.json
COPY scripts/fetch_scanner_models.py /tmp/scanner/fetch_scanner_models.py
RUN python -I /tmp/scanner/fetch_scanner_models.py --manifest /tmp/scanner/models.json \
        --dest /opt/pdfmaster/scanner-models \
    && chmod -R a=rX /opt/pdfmaster/scanner-models && rm -rf /tmp/scanner
ENV SCANNER_MODELS=/opt/pdfmaster/scanner-models
COPY requirements.lock ./
# The scanner must run on the CPU build of onnxruntime and headless OpenCV;
# the GPU wheel or another OpenCV build arriving through a dependency (names
# compared after PEP 503 normalisation) fails the build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr libreoffice-writer libreoffice-impress fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.lock \
    && python -c "import importlib.metadata as m, re, sys; found = {re.sub(r'[-_.]+', '-', d.metadata['Name']).lower() for d in m.distributions()} & {'onnxruntime-gpu', 'opencv-python', 'opencv-contrib-python', 'opencv-contrib-python-headless'}; sys.exit(f'Forbidden packages installed: {sorted(found)}' if found else 0)" \
    && useradd --create-home --uid 10001 pdfmaster
COPY --chown=pdfmaster:pdfmaster . .
RUN mkdir -p /data/private /data/static && chown -R pdfmaster:pdfmaster /data /app
USER pdfmaster
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(h)s %(t)s %(m)s %(U)s %(s)s %(b)s"]
