# Выгрузка продаж FunPay

## Установка
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # вписать golden_key и PHPSESSID из браузера
```

## Первый запуск (отладка)
```
python main.py --inspect
```
Выгружает последние 7 дней, печатает имена полей POST и заголовков (без значений),
ответ сервера, HTML строки таблицы, 3 первые строки JSONL и список ключей.
Если POST не прошёл, сверьте с Network и попробуйте `--csrf-mode header` или `both`.

## После inspect
Заполните `FIELD_MAP` в `models.py` реальными ключами, положите 2–3 замаскированные
строки в `tests/fixtures/real_sample.jsonl`, запустите `pytest`.

## Обычный запуск
```
python main.py --from 2024-01-01 --to 2025-12-31 --out sales.jsonl
python main.py --input sales.jsonl     # итоги по готовому файлу
```
По умолчанию — одна выгрузка на весь период. `--split-days 90` нужен, только если заказов больше 100 000.

Коды выхода: 0 — ок, 1 — ошибка выгрузки/разбора, 2 — cookie устарели, 3 — капча/блокировка.

## HTML-отчёт
```
python report.py --input sales.jsonl --out report.html
python main.py --from 2020-01-01 --html          # выгрузить и сразу собрать отчёт
```
Откройте `report.html` в браузере. Внутри фильтры (период, игра, позиция, статус, покупатель),
динамика, тепловая карта по часам, позиции, покупатели, отзывы, таблица заказов.
В файле ники покупателей — не публикуйте его.
