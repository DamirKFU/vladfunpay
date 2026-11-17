#!/usr/bin/env sh
# Обновление: забрать свежий код и пересобрать контейнеры. Данные сохраняются.
set -e
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
