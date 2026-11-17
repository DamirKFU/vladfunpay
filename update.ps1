# Обновление: забрать свежий код и пересобрать контейнеры. Данные сохраняются.
git pull --ff-only
if ($?) { docker compose up -d --build }
docker image prune -f | Out-Null
