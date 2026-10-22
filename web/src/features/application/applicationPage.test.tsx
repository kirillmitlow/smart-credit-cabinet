import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { blockingA11yViolations } from '@/test/a11y';
import { MockEventSource } from '@/test/eventSource';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { applicationPage, outcomes, timelineSteps } from '@/texts';
import { makeDecision } from '@/test/decisionFactory';

type App = ReturnType<typeof makeApplication>;

function serve(initial: App) {
  let current = initial;
  let requests = 0;
  server.use(
    http.get('*/api/applications/app-1', () => {
      requests += 1;
      return Response.json(current);
    }),
    http.get('*/api/applications/app-1/decision', () =>
      Response.json(
        current.status === 'REJECTED'
          ? makeDecision({
              outcome: 'REJECTED',
              terms: null,
              offer: null,
              whatHelped: [],
              reasons: [
                { code: 'BANK_POLICY', text: 'Сейчас одобрить заявку не можем', action: '' },
              ],
            })
          : makeDecision(),
      ),
    ),
  );
  return {
    set: (next: Partial<App>) => {
      current = { ...current, ...next };
    },
    count: () => requests,
  };
}

const sent = (status: string, extra: Partial<App> = {}) =>
  makeApplication({
    status,
    submittedAt: '2026-10-21T09:04:00Z',
    allowedActions: ['WITHDRAW'],
    ...extra,
  });

describe('страница заявки', () => {
  it('сводка, таймлайн, подпись «обновляется автоматически», доступность', async () => {
    mockSessions({ client: makeMe() });
    serve(sent('CHECKING'));
    const { container } = renderApp('/applications/app-1');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Заявка № АЗ-2026-000001' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Экспресс-кредит: 500.000.₽ на 12.месяцев/)).toBeInTheDocument();
    expect(screen.getByText(applicationPage.autoUpdate)).toBeInTheDocument();

    const list = screen.getByRole('list', { name: applicationPage.timelineLabel });
    const items = Array.from(list.children);
    expect(items).toHaveLength(6);
    expect(items[1]).toHaveAttribute('aria-current', 'step');
    expect(items[1]).toHaveTextContent(timelineSteps[1].title);
    expect(items[1]).toHaveTextContent(timelineSteps[1].running);
    expect(items[0]).toHaveTextContent(/Заявка принята 21\sоктября, 12:04/);
    // шаги озвучиваются вежливой live-областью
    const live = screen.getByTestId('timeline-live');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent(timelineSteps[1].title);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('шаги переключаются сами: опрос сервера без перезагрузки', async () => {
    mockSessions({ client: makeMe() });
    const api = serve(sent('SUBMITTED'));
    renderApp('/applications/app-1');
    await screen.findByText(timelineSteps[0].running);
    api.set({ status: 'CHECKING' });
    expect(
      await screen.findByText(timelineSteps[1].running, undefined, { timeout: 6000 }),
    ).toBeInTheDocument();
    api.set({ status: 'MANUAL_REVIEW' });
    expect(
      await screen.findByText(timelineSteps[2].running, undefined, { timeout: 6000 }),
    ).toBeInTheDocument();
  }, 15_000);

  it('повтор события SSE не дублирует шаг', async () => {
    mockSessions({ client: makeMe() });
    const api = serve(sent('SUBMITTED'));
    renderApp('/applications/app-1');
    await screen.findByText(timelineSteps[0].running);
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    act(() => MockEventSource.latest().open());
    api.set({ status: 'CHECKING' });
    act(() => {
      MockEventSource.latest().emit('status_changed', {}, 7);
      MockEventSource.latest().emit('status_changed', {}, 7);
    });
    await screen.findByText(timelineSteps[1].running);
    expect(screen.getByTestId('timeline').children).toHaveLength(6);
  });

  it('черновик ведёт на форму', async () => {
    mockSessions({ client: makeMe() });
    serve(makeApplication());
    renderApp('/applications/app-1');
    await waitFor(() => expect(window.location.pathname).toBe('/applications/app-1/edit/1'));
  });

  it('чужая или несуществующая заявка', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () =>
        problemResponse({ status: 404, code: 'NOT_FOUND' }),
      ),
    );
    renderApp('/applications/app-1');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Не нашли такую заявку' }),
    ).toBeInTheDocument();
  });

  it('сбой при первой загрузке: «Повторить»', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/applications/app-1', () =>
        problemResponse({ status: 400, code: 'BAD_REQUEST' }),
      ),
    );
    renderApp('/applications/app-1');
    await screen.findByTestId('error-screen');
    serve(sent('CHECKING'));
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('timeline')).toBeInTheDocument();
  });

  it('связь потеряна после загрузки: данные остаются, есть сообщение', async () => {
    mockSessions({ client: makeMe() });
    serve(sent('CHECKING'));
    const { queryClient } = renderApp('/applications/app-1');
    await screen.findByTestId('timeline');
    server.use(
      http.get('*/api/applications/app-1', () =>
        problemResponse({ status: 400, code: 'BAD_REQUEST' }),
      ),
    );
    await act(async () => {
      await queryClient.invalidateQueries();
    });
    expect(await screen.findByTestId('lost-connection')).toHaveTextContent(
      applicationPage.lostConnection,
    );
    expect(screen.getByTestId('timeline')).toBeInTheDocument();
  });
});

describe('блоки исхода', () => {
  it('«Одобрено»: условия решения, «Отказаться» с подтверждением', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    serve(sent('APPROVED', { allowedActions: ['ACCEPT_OFFER', 'WITHDRAW'] }));
    let withdrawKey: string | null = null;
    server.use(
      http.post('*/api/applications/app-1/withdraw', ({ request }) => {
        withdrawKey = request.headers.get('Idempotency-Key');
        return Response.json(sent('WITHDRAWN', { allowedActions: [] }));
      }),
    );
    const { container } = renderApp('/applications/app-1');
    expect(
      await screen.findByRole('heading', { level: 2, name: outcomes.approved.title }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: outcomes.approved.accept })).toBeDisabled();
    expect(await blockingA11yViolations(container)).toEqual([]);

    await user.click(screen.getByRole('button', { name: applicationPage.withdraw.decline }));
    const dialog = await screen.findByRole('dialog', { name: applicationPage.withdraw.title });
    await user.click(
      within(dialog).getByRole('button', { name: applicationPage.withdraw.confirm }),
    );
    expect(await screen.findByText('Заявка отозвана вами')).toBeInTheDocument();
    expect(withdrawKey).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: applicationPage.withdraw.decline }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: applicationPage.closed.newApplication }),
    ).toHaveAttribute('href', '/wizard');
  });

  it('«Отказ»: спокойный блок и «Подобрать другой вариант», без внутренних слов', async () => {
    mockSessions({ client: makeMe() });
    serve(sent('REJECTED', { allowedActions: [] }));
    const { container } = renderApp('/applications/app-1');
    expect(
      await screen.findByRole('heading', { level: 2, name: outcomes.rejected.title }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: outcomes.rejected.pickOther })).toHaveAttribute(
      'href',
      '/wizard',
    );
    expect(screen.getByRole('link', { name: outcomes.rejected.understood })).toHaveAttribute(
      'href',
      '/',
    );
    expect(document.body.textContent).not.toMatch(/грейд|DSCR|стоп-фактор|скоринг/i);
    expect(
      screen.queryByRole('button', { name: applicationPage.withdraw.action }),
    ).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('отзыв отклонён сервером: ошибка в окне, окно остаётся', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    serve(sent('CHECKING'));
    server.use(
      http.post('*/api/applications/app-1/withdraw', () =>
        problemResponse({ status: 409, code: 'INVALID_TRANSITION' }),
      ),
    );
    renderApp('/applications/app-1');
    await user.click(await screen.findByRole('button', { name: applicationPage.withdraw.action }));
    const dialog = await screen.findByRole('dialog');
    await user.click(
      within(dialog).getByRole('button', { name: applicationPage.withdraw.confirm }),
    );
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('статус заявки изменился');
  });

  it.each([
    ['COUNTER_OFFER', outcomes.counter.title],
    ['NEEDS_INFO', outcomes.needsInfo.title],
    ['MANUAL_REVIEW', outcomes.manual.title],
    ['OFFER_ACCEPTED', outcomes.signing.title],
  ])('%s: блок по статусу', async (status, title) => {
    mockSessions({ client: makeMe() });
    serve(sent(status));
    renderApp('/applications/app-1');
    expect(await screen.findByRole('heading', { level: 2, name: title })).toBeInTheDocument();
  });

  it('истекла: пояснение и «Подать новую заявку»', async () => {
    mockSessions({ client: makeMe() });
    serve(sent('EXPIRED', { allowedActions: [] }));
    renderApp('/applications/app-1');
    expect((await screen.findAllByText(applicationPage.closed.expiredNote)).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByRole('link', { name: applicationPage.closed.newApplication }),
    ).toBeInTheDocument();
  });
});
