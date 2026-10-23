import type { QueryClient } from '@tanstack/react-query';
import {
  getListApplicationTasksQueryKey,
  useListApplicationTasks,
  type listApplicationTasksResponse,
} from '@/api/generated/api';
import type { TaskList, TaskOut } from '@/api/generated/model';
import { roundView } from './tasksModel';

/** Успешный ответ списка задач (ошибки уже превращены в AppError общим обработчиком) */
export function unwrapTasks(response: listApplicationTasksResponse): TaskList {
  if (response.status !== 200) throw new Error(`Unexpected status ${response.status}`);
  return response.data;
}

/** Пока ждём ответ другого участника (например, поручителя), список перечитывается сам */
export const TASKS_POLL_MS = 10_000;

/** Задачи заявки: что просит банк, текущий раунд и можно ли отправить ответы */
export function useApplicationTasks(applicationId: string, enabled = true) {
  return useListApplicationTasks(applicationId, {
    query: {
      select: unwrapTasks,
      enabled,
      refetchInterval: (query) => {
        const response = query.state.data;
        if (response?.status !== 200) return false;
        return roundView(response.data).othersMissing.length > 0 ? TASKS_POLL_MS : false;
      },
    },
  });
}

/** Задачи, которые ждут ответа клиента: открытые и доступные текущему участнику */
export function openTasksToAnswer(list: TaskList): TaskOut[] {
  return list.items.filter(
    (task) => task.round === list.currentRound && task.status === 'OPEN' && task.canAnswer,
  );
}

/** Положить свежий ответ мутации в кэш, чтобы экран не ждал перечитывания */
export function putTaskList(client: QueryClient, applicationId: string, list: TaskList): void {
  client.setQueryData<listApplicationTasksResponse>(
    getListApplicationTasksQueryKey(applicationId),
    {
      data: list,
      status: 200,
      headers: new Headers(),
    },
  );
}

/** Подменить одну задачу (после сохранения черновика); `canSubmit` пересчитывает сервер при перечитывании */
export function putTask(client: QueryClient, applicationId: string, task: TaskOut): void {
  client.setQueryData<listApplicationTasksResponse>(
    getListApplicationTasksQueryKey(applicationId),
    (previous) => {
      if (!previous || previous.status !== 200) return previous;
      return {
        ...previous,
        data: {
          ...previous.data,
          items: previous.data.items.map((item) => (item.id === task.id ? task : item)),
        },
      };
    },
  );
}
