import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { makeBankCard } from '@/test/bankFactory';
import { blockingA11yViolations } from '@/test/a11y';
import { makeBankMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { errorTexts } from '@/texts';
import { bankOutbox as t } from '@/texts/bank';

const failed = {
  id: 7,
  applicationId: 'bank-app',
  targetSystem: 'BKI',
  eventType: 'CONSENT_GRANTED',
  status: 'FAILED',
  attempts: 30,
  createdAt: '2026-10-23T08:00:00Z',
  lastError: 'SOURCE_UNAVAILABLE',
  canRetry: true,
  blockedReason: null,
};

describe('повтор доставки (T-365)', () => {
  it('показывает сбой, отправляет ключ один раз и обновляет список без обещания завершённой доставки', async () => {
    mockSessions({ bank: makeBankMe() });
    let queued = false;
    const keys: (string | null)[] = [];
    server.use(
      http.get('*/api/backoffice/outbox', () =>
        Response.json({ items: queued ? [] : [failed], nextCursor: null }),
      ),
      http.post('*/api/backoffice/outbox/7/retry', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        queued = true;
        return Response.json({ id: 7, applicationId: 'bank-app', status: 'PENDING' });
      }),
    );
    const { container } = renderApp('/bank');
    const panel = await screen.findByTestId('bank-outbox');
    await userEvent.click(await within(panel).findByRole('button', { name: t.retry }));
    expect(await within(panel).findByText(t.queued)).toBeInTheDocument();
    expect(await within(panel).findByText(t.empty)).toBeInTheDocument();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^[\da-f-]{36}$/);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('после потери ответа повторяет тот же ключ', async () => {
    mockSessions({ bank: makeBankMe() });
    const keys: (string | null)[] = [];
    server.use(
      http.get('*/api/backoffice/outbox', () =>
        Response.json({ items: [failed], nextCursor: null }),
      ),
      http.post('*/api/backoffice/outbox/7/retry', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        return keys.length === 1
          ? problemResponse({ status: 503, code: 'UNKNOWN_ERROR' })
          : Response.json({ id: 7, applicationId: 'bank-app', status: 'PENDING' });
      }),
    );
    renderApp('/bank');
    await userEvent.click(await screen.findByRole('button', { name: t.retry }));
    await screen.findByText(errorTexts.UNKNOWN_ERROR.text);
    await userEvent.click(
      screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action ?? '' }),
    );
    expect(await screen.findByText(t.queued)).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('не позволяет продлить истёкшее окно, показывает причину', async () => {
    mockSessions({ bank: makeBankMe() });
    server.use(
      http.get('*/api/backoffice/outbox', () =>
        Response.json({
          items: [{ ...failed, canRetry: false, blockedReason: 'EXPIRED' }],
          nextCursor: null,
        }),
      ),
    );
    renderApp('/bank');
    expect(await screen.findByRole('button', { name: t.retry })).toBeDisabled();
    expect(screen.getByText(t.expired)).toBeInTheDocument();
  });

  it('карточка запрашивает сообщения только своей заявки', async () => {
    mockSessions({ bank: makeBankMe() });
    const apps: (string | null)[] = [];
    server.use(
      http.get('*/api/backoffice/applications/bank-app', () => Response.json(makeBankCard())),
      http.get('*/api/backoffice/outbox', ({ request }) => {
        apps.push(new URL(request.url).searchParams.get('applicationId'));
        return Response.json({ items: [], nextCursor: null });
      }),
    );
    renderApp('/bank/applications/bank-app?expectedVersion=3');
    await screen.findByTestId('bank-outbox');
    await waitFor(() => expect(apps).toEqual(['bank-app']));
  });
});
