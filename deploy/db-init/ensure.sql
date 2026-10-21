-- Идемпотентно создаёт пользователя и его базу (T-503). Вызывается из init.sh для каждой пары.
-- Параметры: :role и :db (psql --set), пароль берётся из переменной окружения ENSURE_PASSWORD.
-- В коде секретов нет. В Postgres нет CREATE ... IF NOT EXISTS для баз и ролей,
-- поэтому оператор собирается запросом с проверкой по каталогу и выполняется через \gexec.
\set ON_ERROR_STOP on
\getenv pw ENSURE_PASSWORD

-- Роль: создать, если нет; пароль синхронизируем всегда (сменили .env, повторный up подхватит)
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role', :'pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') \gexec
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'role', :'pw') \gexec

-- База: создать, если нет
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'role')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') \gexec

-- Изоляция database-per-service: подключаться к базе может только её владелец
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db', :'role') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db') \gexec
SELECT format('GRANT ALL ON DATABASE %I TO %I', :'db', :'role') \gexec
