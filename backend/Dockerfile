FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=0
RUN if [ "$INSTALL_DEV" = "1" ]; then pip install -r requirements-dev.txt; \
    else pip install -r requirements.txt; fi

COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "app.application.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
