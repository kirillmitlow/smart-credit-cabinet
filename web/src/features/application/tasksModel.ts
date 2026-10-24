import type { TaskList, TaskOut } from '@/api/generated/model';

/** Правки, которые человек ещё не сохранил: id задачи → текст в поле */
export type Edits = Readonly<Record<string, string>>;

/** Текст в поле: несохранённая правка или черновик с сервера */
export function fieldText(task: TaskOut, edits: Edits): string {
  return Object.hasOwn(edits, task.id) ? (edits[task.id] ?? '') : (task.draftAnswer ?? '');
}

/** Ответ сохранён на сервере и в поле ровно он */
export function isSaved(task: TaskOut, edits: Edits): boolean {
  const text = fieldText(task, edits).trim();
  return text !== '' && text === (task.draftAnswer ?? '').trim();
}

/** Есть что сохранять: в поле текст, и он отличается от того, что на сервере */
export function isDirty(task: TaskOut, edits: Edits): boolean {
  const text = fieldText(task, edits).trim();
  return text !== '' && text !== (task.draftAnswer ?? '').trim();
}

/** «Что именно» и «Где взять» лежат в `details`; другие ключи (служебные коды) не показываем */
export function detailText(task: TaskOut, key: 'what' | 'where'): string | null {
  const value = task.details[key];
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

export type AssigneeKind = 'any' | 'guarantor' | 'member';

export function assigneeKind(task: TaskOut): AssigneeKind {
  if (task.assigneePersonInn !== null) return 'guarantor';
  if (task.assigneeUserId !== null) return 'member';
  return 'any';
}

export interface RoundView {
  /** Все задачи текущего раунда, как их отдал сервер */
  tasks: TaskOut[];
  /** Из них ждут ответа */
  open: TaskOut[];
  /** Ждут ответа и их может выполнить текущий участник */
  mine: TaskOut[];
  /** Ждут ответа от другого участника и пока без ответа */
  othersMissing: TaskOut[];
  /** Раунд уже отправлен: открытых задач нет, но есть отвеченные */
  sent: boolean;
}

export function roundView(list: TaskList): RoundView {
  const tasks = list.items.filter((task) => task.round === list.currentRound);
  const open = tasks.filter((task) => task.status === 'OPEN');
  return {
    tasks,
    open,
    mine: open.filter((task) => task.canAnswer),
    othersMissing: open.filter((task) => !task.canAnswer && task.draftAnswer === null),
    sent: open.length === 0 && tasks.some((task) => task.status === 'ANSWERED'),
  };
}

/**
 * Можно ли отправлять: в поле каждой своей задачи есть текст, а чужие задачи уже отвечены
 * (как проверяет сервер: ответ есть на все задачи раунда).
 */
export function canSubmitRound(view: RoundView, edits: Edits): boolean {
  return (
    view.open.length > 0 &&
    view.mine.every((task) => fieldText(task, edits).trim() !== '') &&
    view.othersMissing.length === 0 &&
    view.open.every((task) => task.documentReady !== false)
  );
}
