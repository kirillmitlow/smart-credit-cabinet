import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import type { BankQueueItem } from '@/api/generated/model';
import { sessionQueryKey } from '@/api/session-keys';
import { blockingA11yViolations } from '@/test/a11y';
import { MockEventSource } from '@/test/eventSource';
import { makeBankMe, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { errorTexts, guards, logout } from '@/texts';
import { bankWorkspace as t } from '@/texts/bank';

function item(overrides: Partial<BankQueueItem> = {}): BankQueueItem {
  return {
    id: 'app-1',
    number: 'АЗ-2026-000001',
    status: 'MANUAL_REVIEW',
    version: 3,
    company: { id: 'company-1', name: 'СтанкоПром', inn: '0012345678', isBankCustomer: true },
    productCode: 'INVESTMENT',
    amountRub: 15000000,
    termMonths: 60,
    waitingSince: '2026-10-21T10:00:00Z',
    waitingSeconds: 30 * 3600,
    overdue: true,
    manualReasons: [
      { code: 'COLLATERAL_REVIEW', title: 'Нужно оценить залог', detail: 'Оборудование' },
    ],
    recommendation: { outcome: 'APPROVED', hint: 'REQUEST_SELLER_DOCUMENT' },
    requiredLevel: 'L1',
    badges: ['CLIENT_ANSWERED'],
    documentReceived: null,
    ...overrides,
  };
}

function queue(items: BankQueueItem[], nextCursor: string | null = null) {
  server.use(http.get('*/api/backoffice/queue', () => Response.json({ items, nextCursor })));
}

describe('очередь банка (TS-030)', () => {
  it('показывает запрос, причину, рекомендацию, ожидание и ссылку с версией; доступен с клавиатуры', async () => {
    mockSessions({ bank: makeBankMe() });
    queue([item()]);
    const { container } = renderApp('/bank');
    const row = await screen.findByTestId('bank-queue-app-1');
    expect(row).toHaveTextContent('СтанкоПром');
    expect(row).toHaveTextContent(/15\s000\s000\s₽/);
    expect(row).toHaveTextContent('Нужно оценить залог');
    expect(row).toHaveTextContent(t.hints.REQUEST_SELLER_DOCUMENT);
    expect(row).toHaveTextContent(t.overdue);
    expect(row).toHaveTextContent(t.badges.CLIENT_ANSWERED);
    expect(within(row).getByRole('link')).toHaveAttribute(
      'href',
      '/bank/applications/app-1?expectedVersion=3',
    );
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('пустое состояние и отсутствие рекомендации не превращаются в одобрение', async () => {
    mockSessions({ bank: makeBankMe() });
    queue([]);
    renderApp('/bank');
    expect(await screen.findByText(t.empty)).toBeInTheDocument();
    queue([item({ recommendation: null, manualReasons: [], badges: ['PIPELINE_ERROR'] })]);
    await userEvent.click(screen.getByRole('button', { name: t.refresh }));
    expect(await screen.findByText(t.noRecommendation)).toBeInTheDocument();
    expect(screen.getByText(t.noReasons)).toBeInTheDocument();
  });

  it('состояние загрузки, ошибка с кодом поддержки и повтор', async () => {
    mockSessions({ bank: makeBankMe() });
    server.use(
      http.get('*/api/backoffice/queue', async () => {
        await delay(70);
        return problemResponse({ status: 503, code: 'UNKNOWN_ERROR', requestId: 'req-bank' });
      }),
    );
    renderApp('/bank');
    expect(await screen.findByText(t.loading)).toBeInTheDocument();
    expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.getByText(/req-bank/)).toBeInTheDocument();
    queue([item()]);
    await userEvent.click(
      screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action ?? '' }),
    );
    expect(await screen.findByText('СтанкоПром')).toBeInTheDocument();
  });

  it('фильтры уходят на сервер и сбрасывают страницу', async () => {
    const user = userEvent.setup();
    mockSessions({ bank: makeBankMe() });
    const requests: URL[] = [];
    server.use(
      http.get('*/api/backoffice/queue', ({ request }) => {
        requests.push(new URL(request.url));
        return Response.json({ items: [], nextCursor: null });
      }),
    );
    renderApp('/bank');
    await screen.findByText(t.empty);
    await user.click(screen.getByRole('combobox', { name: t.statusFilter }));
    await user.click(
      await screen.findByRole('option', { name: t.statusOptions.NEEDS_INFO, hidden: true }),
    );
    await waitFor(() => expect(requests.at(-1)?.searchParams.get('status')).toBe('NEEDS_INFO'));
    expect(await screen.findByText(t.emptyFilter)).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: t.productFilter }));
    await user.click(await screen.findByRole('option', { name: 'Кредитная линия', hidden: true }));
    await waitFor(() =>
      expect(requests.at(-1)?.searchParams.get('productCode')).toBe('CREDIT_LINE'),
    );
    expect(requests.at(-1)?.searchParams.has('cursor')).toBe(false);
  });

  it('следующая страница дополняет таблицу с курсором', async () => {
    mockSessions({ bank: makeBankMe() });
    const cursors: (string | null)[] = [];
    server.use(
      http.get('*/api/backoffice/queue', ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        cursors.push(cursor);
        return Response.json({
          items: [item(cursor ? { id: 'app-2', number: 'АЗ-2' } : {})],
          nextCursor: cursor ? null : 'next-page',
        });
      }),
    );
    renderApp('/bank');
    await screen.findByTestId('bank-queue-app-1');
    await userEvent.click(screen.getByRole('button', { name: t.more }));
    expect(await screen.findByTestId('bank-queue-app-2')).toBeInTheDocument();
    expect(screen.getByTestId('bank-queue-app-1')).toBeInTheDocument();
    expect(cursors).toEqual([null, 'next-page']);
    expect(screen.queryByRole('button', { name: t.more })).not.toBeInTheDocument();
  });

  it('событие банка перечитывает очередь без перезагрузки и подсвечивает новую строку', async () => {
    mockSessions({ bank: makeBankMe() });
    queue([]);
    renderApp('/bank');
    await screen.findByText(t.empty);
    act(() => MockEventSource.latest().open());
    queue([item()]);
    act(() => MockEventSource.latest().emit('status_changed', { applicationId: 'app-1' }, 1));
    const row = await screen.findByTestId('bank-queue-app-1');
    await waitFor(() => expect(row).toHaveAttribute('data-fresh', 'true'));
    expect(MockEventSource.latest().url).toContain('zone=bank');
  });

  it('клиент без bank-cookie видит объяснение и не запрашивает очередь', async () => {
    mockSessions({ client: makeMe() });
    const fetched = vi.fn();
    server.use(
      http.get('*/api/backoffice/queue', () => {
        fetched();
        return Response.json({ items: [], nextCursor: null });
      }),
    );
    renderApp('/bank');
    expect(await screen.findByRole('heading', { name: guards.bankOnly.title })).toBeInTheDocument();
    expect(fetched).not.toHaveBeenCalled();
  });

  it('выход банка очищает его данные, сохраняя клиентский кэш', async () => {
    const client = makeMe();
    mockSessions({ client, bank: makeBankMe() });
    queue([item()]);
    server.use(http.post('*/api/auth/bank-logout', () => new Response(null, { status: 204 })));
    const { queryClient } = renderApp('/bank');
    queryClient.setQueryData(sessionQueryKey('client'), client);
    await screen.findByTestId('bank-queue-app-1');
    await userEvent.click(screen.getByRole('button', { name: logout.action }));
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(window.location.search).toBe('?zone=bank');
    expect(queryClient.getQueryData(sessionQueryKey('client'))).toEqual(client);
    expect(queryClient.getQueryData(sessionQueryKey('bank'))).toBeNull();
    expect(
      queryClient.getQueryCache().findAll({
        predicate: (q) =>
          q.queryKey.some((p) => typeof p === 'string' && p.includes('/backoffice')),
      }),
    ).toHaveLength(0);
  });
});
