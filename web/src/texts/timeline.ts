/** Шесть шагов таймлайна и клиентские названия статусов (60-06, 20-02). Полное наполнение — T-437 */

export const timelineSteps = [
  {
    key: 'submitted',
    title: 'Заявка отправлена',
    running: 'Заявка у нас. Сейчас начнём проверку',
    done: 'Заявка принята {date}',
  },
  {
    key: 'checking',
    title: 'Проверяем данные',
    running: 'Проверяем данные компании и кредитную историю. Обычно до 1 минуты',
    done: 'Данные проверены',
  },
  {
    key: 'evaluating',
    title: 'Оцениваем',
    running: 'Заявку смотрит специалист. Обычно до 1 рабочего дня. Ничего делать не нужно',
    done: 'Оценка завершена',
  },
  {
    key: 'decision',
    title: 'Решение готово',
    running: 'Готовим решение',
    done: 'Решение готово',
  },
  {
    key: 'signing',
    title: 'Подписание',
    running: 'Проверьте документы и подпишите. Подписать может руководитель',
    done: 'Договор подписан {date}',
  },
  {
    key: 'money',
    title: 'Деньги на счёте',
    running: 'Зачисляем…',
    done: '{amount} на счёте {account}',
  },
] as const;

/** Шаг между «Проверяем данные» и «Оцениваем», когда специалист что-то просит */
export const needsHelpStep = {
  title: 'Нужна ваша помощь',
  running: 'Специалист просит: {what}. Зачем: {why}. Срок: до {date}',
  action: 'Ответить',
  done: 'Вы ответили {date}. Продолжаем проверку',
} as const;

export const timelineNotes = {
  withdrawn: 'Заявка отозвана вами',
  expired: 'Срок истёк: заявка закрыта. Можно подать новую',
  expiredResponse: 'Срок ответа истёк: заявка закрыта. Можно подать новую',
  expiredOffer: 'Предложение действовало до {date} и закрыто',
  sourceDelayed:
    'Часть проверок идёт дольше обычного. Мы передали заявку специалисту — он завершит её вручную. Ничего делать не нужно',
} as const;

export const applicationStatusLabels = {
  DRAFT: 'Черновик',
  SUBMITTED: 'Заявка отправлена',
  CHECKING: 'Проверяем данные',
  NEEDS_INFO: 'Нужна ваша помощь',
  MANUAL_REVIEW: 'Заявку смотрит специалист',
  APPROVED: 'Одобрено',
  COUNTER_OFFER: 'Есть другие варианты',
  OFFER_ACCEPTED: 'Ждём подписи',
  SIGNED: 'Договор подписан',
  DISBURSING: 'Зачисляем деньги',
  DISBURSED: 'Деньги на счёте',
  REJECTED: 'Сейчас одобрить не можем',
  WITHDRAWN: 'Заявка отозвана',
  EXPIRED: 'Срок истёк',
} as const;

export type ApplicationStatus = keyof typeof applicationStatusLabels;
