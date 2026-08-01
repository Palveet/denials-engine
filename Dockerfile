FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/denials.db \
    ARTIFACT_DIR=/data/artifacts
WORKDIR /srv/app
RUN apt-get update && apt-get install -y --no-install-recommends \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      shared-mime-info \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY --from=frontend-build /frontend/dist ./app/static
RUN mkdir -p /data/artifacts && useradd --create-home appuser && chown -R appuser:appuser /data /srv/app
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
