import type { TaskList, TaskOut } from '@/api/generated/model';

/** Задача клиенту в форме api: по умолчанию «выписка», как её создаёт конвейер (REVENUE_UNKNOWN) */
export function makeTask(overrides: Partial<TaskOut> = {}): TaskOut {
  return {
    id: 'task-1',
    applicationId: 'app-1',
    round: 1,
    kind: 'DOCUMENT',
    title: 'Загрузите выписку по счёту в другом банке',
    whyText: 'Нам нужно подтвердить вашу выручку: у нас нет ваших оборотов.',
    details: {
      what: 'Выписка в формате 1С не меньше чем за 3 месяца, до 5 МБ',
      where: 'В интернет-банке: Выписка → Выгрузка в 1С',
      reasonCode: 'REVENUE_UNKNOWN',
    },
    assigneeUserId: null,
    assigneePersonInn: null,
    status: 'OPEN',
    expiresAt: null,
    draftAnswer: null,
    answer: null,
    canAnswer: true,
    documentReady: true, // Файловые условия текстовых сценариев выполнены; ошибки проверяются отдельно.
    createdAt: '2026-10-22T09:00:00Z',
    answeredAt: null,
    ...overrides,
  };
}

/** Список задач; `canSubmit` считаем так же, как сервер: у каждой открытой задачи раунда есть ответ */
export function makeTaskList(items: TaskOut[] = [makeTask()], overrides: Partial<TaskList> = {}) {
  const currentRound = Math.max(0, ...items.map((task) => task.round));
  const open = items.filter((task) => task.round === currentRound && task.status === 'OPEN');
  const list: TaskList = {
    items,
    currentRound,
    roundsLimit: 3,
    canSubmit:
      open.length > 0 &&
      open.every((task) => task.draftAnswer !== null && task.documentReady !== false),
    ...overrides,
  };
  return list;
}
