# Build context is the repo root (needs packages/core_py). Builds for linux/arm64 and amd64.
FROM python:3.12-slim

ARG INSTALL_ML=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend

COPY packages/core_py /srv/packages/core_py
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/scripts ./scripts

RUN pip install --no-cache-dir /srv/packages/core_py \
 && if [ "$INSTALL_ML" = "true" ]; then \
      pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
      && pip install --no-cache-dir ".[ml]"; \
    else pip install --no-cache-dir .; fi

RUN useradd --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
