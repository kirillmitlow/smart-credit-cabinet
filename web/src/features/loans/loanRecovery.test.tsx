import { delay, http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { makeMe, problemResponse } from '@/test/factories';
import { makeAnnuityLoan, toListItem } from '@/test/loanFactory';
import { testOffer } from '@/test/contractFactory';
import { errorTexts, loansTexts as t } from '@/texts';

it('T-427: ошибка договора видна отдельно от кредита, повтор восстанавливает ссылку', async () => {
  mockSessions({ client: makeMe() });
  const loan = makeAnnuityLoan();
  let failure = true;
  server.use(
    http.get('*/api/loans/loan-1', () => Response.json(loan)),
    http.get('*/api/applications/app-1/offer', () =>
      failure
        ? problemResponse({ status: 503, code: 'UNKNOWN_ERROR' })
        : Response.json(testOffer({ contractId: 'contract-1' })),
    ),
  );
  renderApp('/loans/loan-1');
  expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: t.detail.schedule })).toBeInTheDocument();
  failure = false;
  await userEvent.click(screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action }));
  expect(await screen.findByRole('link', { name: t.detail.document })).toHaveAttribute(
    'href',
    '/api/contracts/contract-1/document',
  );
});

it('T-427: отсутствующий договор объясняется и может появиться после обновления', async () => {
  mockSessions({ client: makeMe() });
  let available = false;
  server.use(
    http.get('*/api/loans/loan-1', () => Response.json(makeAnnuityLoan())),
    http.get('*/api/applications/app-1/offer', () =>
      available
        ? Response.json(testOffer({ contractId: 'contract-1' }))
        : problemResponse({ status: 404, code: 'NOT_FOUND' }),
    ),
  );
  renderApp('/loans/loan-1');
  expect(await screen.findByText(t.detail.documentMissing)).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: t.detail.document })).not.toBeInTheDocument();
  available = true;
  await userEvent.click(screen.getByRole('button', { name: t.detail.documentRefresh }));
  expect(await screen.findByRole('link', { name: t.detail.document })).toBeInTheDocument();
});

it('T-427: следующая страница добавляется один раз, ошибка не стирает предыдущую, повтор использует тот же курсор', async () => {
  mockSessions({ client: makeMe() });
  const first = toListItem(makeAnnuityLoan());
  const second = toListItem(makeAnnuityLoan({ id: 'loan-2', contractNumber: 'КД-2026-000002' }));
  const requests: (string | null)[] = [];
  let failure = true;
  server.use(
    http.get('*/api/loans', async ({ request }) => {
      const url = new URL(request.url);
      const cursor = url.searchParams.get('cursor');
      expect(url.searchParams.get('limit')).toBe('100');
      requests.push(cursor);
      if (!cursor) return Response.json({ items: [first], nextCursor: 'next-page' });
      expect(cursor).toBe('next-page');
      await delay(50);
      return failure
        ? problemResponse({ status: 503, code: 'UNKNOWN_ERROR' })
        : Response.json({ items: [first, second], nextCursor: null });
    }),
  );
  renderApp('/loans');
  const more = await screen.findByRole('button', { name: t.loadMore });
  await userEvent.dblClick(more);
  expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
  expect(screen.getAllByTestId('loan-card')).toHaveLength(1);
  expect(requests).toEqual([null, 'next-page']);
  failure = false;
  await userEvent.click(screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action }));
  await waitFor(() => expect(screen.getAllByTestId('loan-card')).toHaveLength(2));
  expect(requests).toEqual([null, 'next-page', 'next-page']);
  expect(screen.queryByRole('button', { name: t.loadMore })).not.toBeInTheDocument();
});
