import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it } from 'vitest';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { makeTask, makeTaskList } from '@/test/tasksFactory';
import { emptyStates, home } from '@/texts';

it('ошибка списка не выдаётся за отсутствие задач; повтор восстанавливает страницу', async () => {
  mockSessions({ client: makeMe() });
  let failed = true;
  server.use(
    http.get('*/api/applications', () =>
      failed
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json({ items: [], nextCursor: null }),
    ),
  );
  const user = userEvent.setup();
  renderApp('/');
  const tasks = within(
    (await screen.findByRole('heading', { name: home.tasks.heading })).closest('section')!,
  );
  expect(await tasks.findByText(home.tasks.loadFailed)).toBeInTheDocument();
  expect(tasks.queryByText(emptyStates.tasks)).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: home.needMoney })).toBeInTheDocument();
  expect(await screen.findByText(emptyStates.loans)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: home.startDirect })).not.toBeInTheDocument();
  failed = false;
  await user.click(tasks.getByRole('button', { name: home.tasks.retry }));
  expect(await tasks.findByText(emptyStates.tasks)).toBeInTheDocument();
  expect(tasks.queryByText(home.tasks.loadFailed)).not.toBeInTheDocument();
});

it('ошибка задач сохраняет ссылку на заявку и позволяет повторить только их загрузку', async () => {
  mockSessions({ client: makeMe() });
  let taskRequests = 0;
  let listRequests = 0;
  server.use(
    http.get('*/api/applications', () => {
      listRequests += 1;
      return Response.json({
        items: [
          makeApplication({ id: 'respond', status: 'NEEDS_INFO', allowedActions: ['RESPOND'] }),
        ],
        nextCursor: null,
      });
    }),
    http.get('*/api/applications/respond/tasks', () => {
      taskRequests += 1;
      return taskRequests === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json(
            makeTaskList([
              makeTask({ applicationId: 'respond', title: 'Подтвердите поступления' }),
            ]),
          );
    }),
  );
  const user = userEvent.setup();
  renderApp('/');
  const tasks = within(
    (await screen.findByRole('heading', { name: home.tasks.heading })).closest('section')!,
  );
  await tasks.findByText(home.tasks.loadFailed);
  expect(tasks.getByRole('link', { name: home.tasks.open })).toHaveAttribute(
    'href',
    '/applications/respond',
  );
  await user.click(tasks.getByRole('button', { name: home.tasks.retry }));
  expect(await tasks.findByText(/Подтвердите поступления/)).toBeInTheDocument();
  expect(tasks.queryByText(home.tasks.loadFailed)).not.toBeInTheDocument();
  expect(taskRequests).toBe(2);
  expect(listRequests).toBe(1);
});

it('следующие страницы не теряют заявки при ошибке; повтор использует прежний cursor без дублей', async () => {
  mockSessions({ client: makeMe() });
  let nextCalls = 0;
  const cursors: (string | null)[] = [];
  const first = makeApplication({
    id: 'first',
    number: 'АЗ-2026-000010',
    status: 'REJECTED',
    allowedActions: [],
  });
  const second = makeApplication({
    id: 'second',
    number: 'АЗ-2026-000009',
    status: 'APPROVED',
    allowedActions: ['ACCEPT_OFFER'],
  });
  server.use(
    http.get('*/api/applications', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      cursors.push(cursor);
      if (!cursor) return Response.json({ items: [first], nextCursor: 'cursor-older' });
      nextCalls += 1;
      return nextCalls === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json({ items: [first, second], nextCursor: null });
    }),
  );
  const user = userEvent.setup();
  renderApp('/');
  await screen.findByTestId('application-card');
  expect(screen.queryByRole('button', { name: home.startDirect })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: home.applications.loadMore }));
  const section = within(
    screen.getByRole('heading', { name: home.applications.heading }).closest('section')!,
  );
  await section.findByRole('alert');
  expect(section.getAllByTestId('application-card')).toHaveLength(1);
  await user.dblClick(section.getByRole('button', { name: /Повторить/ }));
  await waitFor(() => expect(section.getAllByTestId('application-card')).toHaveLength(2));
  expect(cursors).toEqual([null, 'cursor-older', 'cursor-older']);
  expect(
    await screen.findByText(/Посмотреть решение по заявке № АЗ-2026-000009/),
  ).toBeInTheDocument();
  expect(
    section.queryByRole('button', { name: home.applications.loadMore }),
  ).not.toBeInTheDocument();
});
