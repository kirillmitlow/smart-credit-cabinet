import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { AnswerBody, TaskOut } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeApplication, makeCompanyChoice, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { makeTask, makeTaskList } from '@/test/tasksFactory';
import { clientTasks as t, errorTexts, fill, outcomes, timelineSteps } from '@/texts';

const needsInfo = () =>
  makeApplication({
    status: 'NEEDS_INFO',
    submittedAt: '2026-10-21T09:04:00Z',
    allowedActions: ['RESPOND', 'WITHDRAW'],
  });

interface Served {
  answers: { taskId: string; body: AnswerBody }[];
  submits: () => number;
  tasks: () => TaskOut[];
}

/** Сервер задач и заявки с памятью: ответ сохраняется в черновик, отправка переводит заявку в проверку */
function serveRound(
  initial: TaskOut[],
  options: {
    answerError?: () => Response | null;
    submitError?: () => Response | null;
  } = {},
): Served {
  let application = needsInfo();
  let tasks = initial;
  let submits = 0;
  const answers: Served['answers'] = [];
  server.use(
    http.get('*/api/applications/app-1', () => Response.json(application)),
    http.get('*/api/applications/app-1/tasks', () => Response.json(makeTaskList(tasks))),
    http.post('*/api/tasks/:taskId/answer', async ({ params, request }) => {
      const body = (await request.json()) as AnswerBody;
      const taskId = String(params.taskId);
      answers.push({ taskId, body });
      const failure = options.answerError?.() ?? null;
      if (failure) return failure;
      tasks = tasks.map((task) =>
        task.id === taskId ? { ...task, draftAnswer: body.text } : task,
      );
      return Response.json(tasks.find((task) => task.id === taskId));
    }),
    http.post('*/api/applications/app-1/tasks/submit', async () => {
      submits += 1;
      await delay(40);
      const failure = options.submitError?.() ?? null;
      if (failure) return failure;
      tasks = tasks.map((task) =>
        task.status === 'OPEN'
          ? { ...task, status: 'ANSWERED', answer: task.draftAnswer, draftAnswer: null }
          : task,
      );
      application = { ...application, status: 'CHECKING', allowedActions: ['WITHDRAW'] };
      return Response.json(makeTaskList(tasks));
    }),
  );
  return { answers, submits: () => submits, tasks: () => tasks };
}

const submitButton = () => screen.getByRole('button', { name: t.submit });
const draftButton = () => screen.getByRole('button', { name: t.saveDraft });

describe('блок «Нужна информация» (T-424)', () => {
  it('даёт загрузить выписку в задаче подтверждения выручки', async () => {
    mockSessions({ client: makeMe() });
    serveRound([makeTask({ kind: 'CONFIRM_REVENUE' })]);
    renderApp('/applications/app-1');
    expect(await screen.findByLabelText('Прикрепить документ')).toBeInTheDocument();
  });
  it('показывает, что просят, зачем, срок, кто отвечает и номер раунда; без внутренних кодов', async () => {
    mockSessions({ client: makeMe() });
    serveRound([makeTask()]);
    const { container } = renderApp('/applications/app-1');
    expect(
      await screen.findByRole('heading', { level: 2, name: outcomes.needsInfo.title }),
    ).toBeInTheDocument();
    expect(await screen.findByText(fill(t.round, { round: 1, limit: 3 }))).toBeInTheDocument();
    const item = within(await screen.findByTestId('info-task'));
    expect(item.getByRole('heading', { level: 3 })).toHaveTextContent(
      'Загрузите выписку по счёту в другом банке',
    );
    expect(item.getByText(/Нам нужно подтвердить вашу выручку/)).toBeInTheDocument();
    expect(item.getByText(/Выписка в формате 1С не меньше чем за 3 месяца/)).toBeInTheDocument();
    expect(item.getByText(/Выписка → Выгрузка в 1С/)).toBeInTheDocument();
    expect(item.getByText(t.deadlineNone, { exact: false })).toBeInTheDocument();
    expect(item.getByText(t.assignees.any, { exact: false })).toBeInTheDocument();
    expect(item.queryByText(t.fileLater)).not.toBeInTheDocument();
    expect(item.getByRole('button', { name: 'Загрузить файл' })).toBeDisabled();
    expect(item.getByLabelText('Прикрепить документ')).toBeInTheDocument();
    // таймлайн на этом же экране показывает паузу «Нужна ваша помощь»
    expect(screen.getByTestId('timeline')).toHaveTextContent('Нужна ваша помощь');

    const text = container.textContent ?? '';
    for (const code of ['REVENUE_UNKNOWN', 'DOCUMENT', 'NEEDS_INFO', 'OPEN', 'ROUND_']) {
      expect(text).not.toContain(code);
    }
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('срок показывается, когда таймер включён', async () => {
    mockSessions({ client: makeMe() });
    serveRound([makeTask({ expiresAt: '2026-10-26T09:00:00Z' })]);
    renderApp('/applications/app-1');
    const item = within(await screen.findByTestId('info-task'));
    expect(item.getByText(/до 26\sокт\s2026/)).toBeInTheDocument();
    expect(item.queryByText(t.deadlineNone, { exact: false })).toBeNull();
  });

  it('«Отправить ответы» доступна, только когда заполнено всё', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    serveRound([
      makeTask({ id: 'task-1' }),
      makeTask({ id: 'task-2', kind: 'EXPLANATION', title: 'Почему упала выручка в марте?' }),
    ]);
    renderApp('/applications/app-1');
    await screen.findAllByTestId('info-task');
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText(t.needAll)).toBeInTheDocument();
    const [first, second] = screen.getAllByRole('textbox');
    await user.type(first!, 'Выписка в другом банке есть, пришлём позже');
    expect(submitButton()).toBeDisabled();
    await user.type(second!, 'В марте был ремонт склада');
    expect(submitButton()).toBeEnabled();
    await user.clear(second!);
    expect(submitButton()).toBeDisabled();
  });

  it('черновик сохраняется и возвращается после перезагрузки страницы', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const api = serveRound([makeTask()]);
    const first = renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    expect(draftButton()).toBeDisabled();
    await user.type(screen.getByRole('textbox'), '  Пришлём выписку завтра  ');
    expect(screen.getByText(t.draftDirty)).toBeInTheDocument();
    await user.click(draftButton());
    expect(await screen.findByText(t.draftSaved)).toBeInTheDocument();
    expect(api.answers).toEqual([
      { taskId: 'task-1', body: { text: 'Пришлём выписку завтра', submitRound: false } },
    ]);
    expect(draftButton()).toBeDisabled();
    // заявка осталась в «Нужна информация», банку ничего не ушло
    expect(api.submits()).toBe(0);
    expect(screen.queryByTestId('recheck-note')).toBeNull();

    first.unmount();
    renderApp('/applications/app-1');
    expect(await screen.findByDisplayValue('Пришлём выписку завтра')).toBeInTheDocument();
    expect(screen.getByText(t.draftSaved)).toBeInTheDocument();
  });

  it('отправка: ответы сохраняются, раунд уходит банку, страница показывает «Проверяем заново»', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const api = serveRound([makeTask()]);
    const { container } = renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    await user.type(screen.getByRole('textbox'), 'Выписка за июль–сентябрь, номер счёта в письме');
    await user.click(submitButton());

    const note = await screen.findByTestId('recheck-note');
    expect(note).toHaveTextContent(t.sentTitle);
    expect(note).toHaveTextContent(t.sent);
    // несохранённый ответ ушёл вместе с отправкой
    expect(api.answers).toHaveLength(1);
    expect(api.answers[0]?.body.text).toBe('Выписка за июль–сентябрь, номер счёта в письме');
    expect(api.submits()).toBe(1);
    // блок задач исчез, таймлайн показывает проверку
    expect(screen.queryByTestId('info-task')).toBeNull();
    expect(screen.queryByRole('heading', { name: outcomes.needsInfo.title })).toBeNull();
    expect(screen.getByTestId('timeline-live')).toHaveTextContent(timelineSteps[1].title);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('двойное нажатие «Отправить ответы» даёт один запрос', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const api = serveRound([makeTask()]);
    renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    await user.type(screen.getByRole('textbox'), 'Ответ');
    await user.dblClick(submitButton());
    await screen.findByTestId('recheck-note');
    expect(api.submits()).toBe(1);
    expect(api.answers).toHaveLength(1);
  });

  it('409 ROUND_INCOMPLETE: понятный текст, ответ не теряется, можно повторить', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    let fail = true;
    serveRound([makeTask()], {
      submitError: () => {
        if (!fail) return null;
        fail = false;
        return problemResponse({ status: 409, code: 'ROUND_INCOMPLETE', requestId: 'req-round' });
      },
    });
    renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    await user.type(screen.getByRole('textbox'), 'Мой ответ');
    await user.click(submitButton());
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.ROUND_INCOMPLETE.text);
    expect(alert).toHaveAttribute('data-error-code', 'ROUND_INCOMPLETE');
    expect(alert).toHaveTextContent('req-round');
    expect(alert.textContent).not.toContain('Служебное описание');
    expect(screen.getByRole('textbox')).toHaveValue('Мой ответ');
    // повтор проходит
    await waitFor(() => expect(submitButton()).toBeEnabled());
    await user.click(submitButton());
    await screen.findByTestId('recheck-note');
  });

  it('409 TASK_CLOSED при сохранении: текст из словаря, без кода', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    serveRound([makeTask()], {
      answerError: () => problemResponse({ status: 409, code: 'TASK_CLOSED' }),
    });
    const { container } = renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    await user.type(screen.getByRole('textbox'), 'Поздно');
    await user.click(draftButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(errorTexts.TASK_CLOSED.text);
    expect(container.textContent).not.toContain('TASK_CLOSED');
    expect(screen.getByRole('textbox')).toHaveValue('Поздно');
  });

  it('409 ROUND_ALREADY_SENT (раунд ушёл в другой вкладке): страница обновляется до проверки', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    let application = needsInfo();
    server.use(
      http.get('*/api/applications/app-1', () => Response.json(application)),
      http.get('*/api/applications/app-1/tasks', () => Response.json(makeTaskList())),
      http.post('*/api/tasks/:taskId/answer', () => Response.json(makeTask({ draftAnswer: 'a' }))),
      http.post('*/api/applications/app-1/tasks/submit', () => {
        application = { ...application, status: 'CHECKING', allowedActions: ['WITHDRAW'] };
        return problemResponse({ status: 409, code: 'ROUND_ALREADY_SENT' });
      }),
    );
    renderApp('/applications/app-1');
    await screen.findByTestId('info-task');
    await user.type(screen.getByRole('textbox'), 'a');
    await user.click(submitButton());
    await waitFor(() => expect(screen.queryByTestId('info-task')).toBeNull());
    expect(screen.getByTestId('timeline-live')).toHaveTextContent(timelineSteps[1].title);
  });

  it('задач не загрузилось: ошибка с повтором, остальная страница работает', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () => Response.json(needsInfo())),
      http.get('*/api/applications/app-1/tasks', () =>
        problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' }),
      ),
    );
    renderApp('/applications/app-1');
    expect(await screen.findByText(errorTexts.SERVICE_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.getByTestId('timeline')).toBeInTheDocument();
  });

  it('раунд ещё не создан: просим обновить, а не показываем пустую форму', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () => Response.json(needsInfo())),
      http.get('*/api/applications/app-1/tasks', () => Response.json(makeTaskList([]))),
    );
    renderApp('/applications/app-1');
    expect(await screen.findByText(t.preparing)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t.submit })).toBeNull();
  });

  describe('участники и поручитель', () => {
    it('чужую задачу не заполняем: видно, кто отвечает, а отправить нельзя, пока он не ответил', async () => {
      const user = userEvent.setup();
      mockSessions({ client: makeMe() });
      serveRound([
        makeTask({ id: 'task-1' }),
        makeTask({
          id: 'task-g',
          kind: 'GUARANTOR',
          title: 'Подтвердите согласие поручителя',
          assigneePersonInn: '770700000001',
          canAnswer: false,
        }),
      ]);
      renderApp('/applications/app-1');
      const items = await screen.findAllByTestId('info-task');
      expect(items).toHaveLength(2);
      expect(within(items[1]!).queryByRole('textbox')).toBeNull();
      expect(within(items[1]!).getByText(t.notYours)).toBeInTheDocument();
      expect(
        within(items[1]!).getByText(t.assignees.guarantor, { exact: false }),
      ).toBeInTheDocument();
      await user.type(screen.getByRole('textbox'), 'Мой ответ');
      expect(submitButton()).toBeDisabled();
      expect(screen.getByText(t.waitingOthers)).toBeInTheDocument();
    });

    it('когда другой участник уже ответил, отправить можно', async () => {
      const user = userEvent.setup();
      mockSessions({ client: makeMe() });
      serveRound([
        makeTask({ id: 'task-1' }),
        makeTask({
          id: 'task-g',
          kind: 'GUARANTOR',
          title: 'Подтвердите согласие поручителя',
          assigneePersonInn: '770700000001',
          canAnswer: false,
          draftAnswer: 'Согласен быть поручителем',
        }),
      ]);
      renderApp('/applications/app-1');
      await screen.findAllByTestId('info-task');
      expect(screen.getByText(/Согласен быть поручителем/)).toBeInTheDocument();
      await user.type(screen.getByRole('textbox'), 'Мой ответ');
      expect(submitButton()).toBeEnabled();
    });

    it('поручитель видит только свою задачу и не может отправить раунд', async () => {
      const user = userEvent.setup();
      mockSessions({
        client: makeMe({ companies: [makeCompanyChoice({}, 'GUARANTOR')] }),
      });
      const api = serveRound([
        makeTask({
          id: 'task-g',
          kind: 'GUARANTOR',
          title: 'Подтвердите согласие поручителя',
          assigneePersonInn: '770700000001',
        }),
      ]);
      renderApp('/applications/app-1');
      const items = await screen.findAllByTestId('info-task');
      expect(items).toHaveLength(1);
      expect(items[0]).toHaveTextContent('Подтвердите согласие поручителя');
      expect(screen.queryByText('Загрузите выписку по счёту в другом банке')).toBeNull();
      expect(screen.queryByRole('button', { name: t.submit })).toBeNull();
      expect(screen.getByText(t.guarantorNote)).toBeInTheDocument();
      await user.type(screen.getByRole('textbox'), 'Подтверждаю');
      await user.click(screen.getByRole('button', { name: t.saveAnswer }));
      expect(await screen.findByText(t.draftSaved)).toBeInTheDocument();
      expect(api.answers).toEqual([
        { taskId: 'task-g', body: { text: 'Подтверждаю', submitRound: false } },
      ]);
      expect(api.submits()).toBe(0);
    });
  });
});
