import type { ApplicationOut } from '@/api/generated/model';
import { fill, home } from '@/texts';

export interface HomeTask {
  key: string;
  label: string;
  to: string;
}

/**
 * «Что нужно от вас» из заявок: что клиенту предстоит сделать сейчас, видно по `allowedActions`.
 * Задачи банка (запросы выписки и т.п.) придут отдельной ручкой (T-350): тогда они добавятся к этим.
 */
export function tasksFrom(applications: readonly ApplicationOut[]): HomeTask[] {
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
      tasks.push({
        key: `${application.id}:respond`,
        label: fill(home.tasks.respond, values),
        to: page,
      });
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
