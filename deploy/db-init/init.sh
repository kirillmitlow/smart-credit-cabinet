#!/usr/bin/env bash
# One-shot контейнер db-init (T-503): базы и пользователи на любом томе Postgres, повторный запуск безопасен.
# Пароли приходят из окружения (POSTGRES_PASSWORD для api, MOCK_DB_PASSWORD для моков), в файле их нет.
set -euo pipefail

: "${PGPASSWORD:?PGPASSWORD (пароль суперпользователя) не задан}"
: "${API_DB_PASSWORD:?API_DB_PASSWORD не задан}"
: "${MOCK_DB_PASSWORD:?MOCK_DB_PASSWORD не задан}"

# Ждать Postgres не нужно: compose запускает нас после service_healthy.
ensure() { # ensure <имя роли и базы> <пароль>
    echo "db-init: $1"
    ENSURE_PASSWORD="$2" psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 \
        --dbname=postgres --set=role="$1" --set=db="$1" --file=/db-init/ensure.sql
}

ensure api "$API_DB_PASSWORD"
for name in registry tax bki bank_core scenarios; do
    ensure "mock_${name}" "$MOCK_DB_PASSWORD"
done
echo "db-init: готово"
