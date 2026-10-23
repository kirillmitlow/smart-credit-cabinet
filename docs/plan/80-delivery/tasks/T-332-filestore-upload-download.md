# T-332. Реализовать `FileStore` в Postgres, загрузку и скачивание документов

| | |
|---|---|
| Статус | REVIEW — хранилище/HTTP; подключение сохранённого PDF к подписи — T-336 |
| Владелец | Агент C (Codex 2), D-113 |
| Ветка | `feat/c-documents-storage` |
| Оценка | ~6 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-201](T-201-db-and-migrations.md), [T-210](T-210-auth-sessions.md), [T-250](T-250-applications-model-api.md), [T-252](T-252-events-and-audit.md) |

## Цель

Файлы клиента хранятся неизменяемо и надёжно, скачиваются только через `api` с проверкой прав; проверки при загрузке дают понятные коды ошибок.

## Входит / не входит

- **Входит:** интерфейс `FileStore` (`put/get/delete`) с реализацией «Postgres `bytea`» (`document_blobs`), таблица `documents` с видами, происхождением (`UPLOADED/DEMO_GENERATED/SYSTEM_GENERATED`), `template_version`, `sha256`, `parse_status`, `parsed`; `POST /documents` (multipart), проверки 1–4 из [50-12](../../50-architecture/12-files-and-documents.md): размер по ходу чтения (`FILE_TOO_LARGE`), тип по содержимому, PDF не зашифрован и ≤ 30 страниц, кодировка и ≤ 100 000 строк; не более 10 файлов и 50 МБ на заявку; `GET /documents/{id}`, `GET /documents/{id}/download` (`Content-Disposition: attachment`, `nosniff`), права по компании; имя клиента — только для показа; события `FILE_UPLOADED`, `FILE_DOWNLOADED`, `DOCUMENT_GENERATED`; «заменить» = новый файл + отмена прежнего.
- **Не входит:** разбор выписки ([T-333](T-333-statement-parse-task.md)); генерация PDF ([T-336](T-336-pdf-generation-weasyprint.md)).

## Входные документы

- [50-12](../../50-architecture/12-files-and-documents.md): Файлы и документы
- [50-09](../../50-architecture/09-security.md): Безопасность
- [50-06](../../50-architecture/06-data-model.md): Модель данных базы `api`
- [00-05](../../00-meta/05-decisions-index.md): Реестр решений

## Критерии приёмки

- [x] «PDF» с расширением `.txt`, файл больше лимита, зашифрованный PDF — понятные отказы (тесты [70-01](../../70-quality/01-test-strategy.md))
- [x] Чужая компания → `404`
- [ ] Хеш считается при записи и проверяется при выдаче на подпись
- [x] Имя файла клиента никогда не используется как путь
- [x] Тесты написаны и зелёные (`make check`)
- [x] Документация и OpenAPI обновлены, если менялся контракт
- [x] Запись в журнале

## Тесты

integration: загрузка, лимиты, права; unit: определение типа по содержимому.

## Заметки для реализации

- Антивирус не ставим (README: «в промышленной системе — проверка на загрузке») — [50-12](../../50-architecture/12-files-and-documents.md).
- Первый пакет C: отдельные неизменяемые bytea, streaming multipart, 10 файлов /
  50 МиБ на заявку, замена новым исходником, права и ключ повторов, аудит в одной
  транзакции, полный/выборочный reset и hold во время чтения. 17 unit + 13 integration.
- [Публичный интерфейс](../../../../api/app/modules/documents/README.md).
  HTTP-композиция в app.documents_http/app.document_actions не даёт нижнему
  documents импортировать верхние applications/auth; R1/R5 не ослабляются.
- SHA-256 считается при записи и проверяется в verified_content и при скачивании.
  Контракт пока JSON; привязка сохранённого PDF к подписи входит в T-336.
  Парсер/подтверждение — следующий пакет T-330…334: файл пока PENDING и не влияет на решение.
