/**
 * Тексты ошибок по `code` из problem+json (60-06, «Тексты ошибок»; 50-07).
 * Фронт показывает текст из словаря, а не `detail` сервера. Три части: что случилось, почему, что делать.
 */

export interface ErrorText {
  /** Фраза для человека; подстановки в фигурных скобках */
  text: string;
  /** Подпись кнопки действия, если оно есть */
  action?: string;
}

export const errorTexts = {
  UNAUTHENTICATED: { text: 'Сессия закончилась. Войдите снова', action: 'Войти' },
  ROLE_CANNOT_SIGN: {
    text: 'Подписать может только руководитель. Передайте ему заявку',
    action: 'Передать руководителю',
  },
  INN_INVALID: {
    text: 'В ИНН должно быть 10 цифр для компании или 12 для ИП. Проверьте номер',
  },
  NOT_FOUND: { text: 'Не нашли такую страницу или заявку', action: 'На главную' },
  VERSION_CONFLICT: {
    text: 'Заявку изменили в другой вкладке. Обновите, чтобы не потерять данные',
    action: 'Обновить',
  },
  DUPLICATE_APPLICATION: {
    text: 'У вас уже есть заявка в работе. Новую можно подать после решения по ней',
    action: 'Открыть заявку',
  },
  INVALID_TRANSITION: {
    text: 'Это действие сейчас недоступно: статус заявки изменился',
    action: 'Обновить',
  },
  CONSENT_REQUIRED: {
    text: 'Без согласия на запрос в кредитную историю мы не сможем проверить заявку',
    action: 'Вернуться к согласиям',
  },
  VALIDATION_ERROR: {
    text: 'Проверьте поля, отмеченные красным. Рядом с каждым написано, что не так',
  },
  BAD_REQUEST: { text: 'Не получилось обработать запрос. Проверьте данные и попробуйте ещё раз' },
  IDEMPOTENCY_IN_PROGRESS: { text: 'Секунду, предыдущее действие ещё выполняется' },
  IDEMPOTENCY_KEY_REUSED: {
    text: 'Это действие уже выполнено с другими данными. Обновите страницу и повторите',
    action: 'Обновить',
  },
  CONFLICT: { text: 'Данные изменились. Обновите страницу и повторите', action: 'Обновить' },
  RATE_LIMITED: { text: 'Слишком много попыток. Подождите минуту' },
  SERVICE_UNAVAILABLE: {
    text: 'Сервис временно недоступен. Ваши данные сохранены',
    action: 'Повторить',
  },
  DEMO_MODE_DISABLED: {
    text: 'Демо-режим выключен. Эта страница недоступна',
    action: 'На главную',
  },
  NETWORK_ERROR: {
    text: 'Нет связи с сервером. Как только появится, продолжим',
    action: 'Повторить',
  },
  UNKNOWN_ERROR: { text: 'Что-то пошло не так. Попробуйте ещё раз', action: 'Повторить' },
} as const satisfies Record<string, ErrorText>;

export type KnownErrorCode = keyof typeof errorTexts;

/** Для `429` с `Retry-After`: точнее, чем «подождите минуту» */
export const retryAfterText = 'Слишком много попыток. Повторите через {seconds}';

/** Мелкая строка под ошибкой; номер запроса нужен поддержке */
export const supportCodeLabel = 'Код для поддержки: {requestId}';
export const copySupportCode = 'Скопировать код';
export const supportCodeCopied = 'Код скопирован';

/** Неизвестный `code` не роняет приложение: общий текст плюс номер запроса */
export const genericError = errorTexts.UNKNOWN_ERROR;

/** Отдельные тексты, у которых нет `code` в API (60-06) */
export const otherErrors = {
  wrongLoginCode: 'Код не подошёл. Осталось {attempts}',
  newCodeAction: 'Получить новый',
  fileUnreadable: 'Этот файл не получилось прочитать. Нужна выписка в формате 1С (текстовый файл)',
  chooseOtherFile: 'Выбрать другой',
  offlineBar: 'Нет связи',
} as const;
