import type { ApplicationOut, TaskList } from '@/api/generated/model';
import { openTasksToAnswer } from '@/features/application/useTasks';
import { clientTasks, fill, home } from '@/texts';

export interface HomeTask {
  key: string;
  label: string;
  to: string;
}

/**
 * «Что нужно от вас» из заявок: что клиенту предстоит сделать сейчас, видно по `allowedActions`.
 * Запросы банка (T-424) берутся из задач заявки (`tasksByApplication`): по строке на каждую открытую
 * задачу, которую может выполнить этот участник. Пока задачи не загрузились (или не загрузились
 * совсем), показываем общую строку «Ответить специалисту».
 */
export function tasksFrom(
  applications: readonly ApplicationOut[],
  tasksByApplication: ReadonlyMap<string, TaskList> = new Map(),
): HomeTask[] {
  const tasks: HomeTask[] = [];
  for (const application of applications) {
    const values = { number: application.number };
    const page = `/applications/${application.id}`;
    const actions = application.allowedActions;
    if (application.status === 'DRAFT' && actions.includes('EDIT_DRAFT')) {
      tasks.push({
        key: `${application.id}:draft`,
        label: fill(home.tasks.draft, values),
        to: `${page}/edit/1`,
      });
    } else if (actions.includes('RESPOND')) {
      const loaded = tasksByApplication.get(application.id);
      if (!loaded) {
        tasks.push({
          key: `${application.id}:respond`,
          label: fill(home.tasks.respond, values),
          to: page,
        });
      } else {
        for (const task of openTasksToAnswer(loaded)) {
          tasks.push({
            key: `${application.id}:task:${task.id}`,
            label: fill(clientTasks.home.answer, { title: task.title, number: application.number }),
            to: page,
          });
        }
      }
    } else if (actions.includes('ACCEPT_OFFER')) {
      tasks.push({
        key: `${application.id}:decision`,
        label: fill(home.tasks.decision, values),
        to: page,
      });
    } else if (actions.includes('SIGN')) {
      tasks.push({ key: `${application.id}:sign`, label: fill(home.tasks.sign, values), to: page });
    }
  }
  return tasks;
}
