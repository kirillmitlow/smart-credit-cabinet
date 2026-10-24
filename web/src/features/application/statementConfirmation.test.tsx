import { http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ConfirmStatementIn, DocumentOut } from '@/api/generated/model';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { documentTexts as dt } from '@/texts/documents';
import { DocumentFiles } from './DocumentFiles';

function document(): DocumentOut {
  return {
    id: 'doc-1',
    applicationId: 'app-1',
    companyId: 'company-1',
    taskId: 'task-1',
    kind: 'BANK_STATEMENT_1C',
    origin: 'UPLOADED',
    filename: 'statement.txt',
    mime: 'text/plain',
    sizeBytes: 100,
    sha256: 'a'.repeat(64),
    parseStatus: 'PARSED',
    parseError: null,
    confirmedAt: null,
    cancelledAt: null,
    createdAt: '2026-10-21T12:00:00Z',
    parsed: {
      months: ['2026-01', '2026-02', '2026-03', '2026-04'].map((month, index) => ({
        month,
        complete: index < 3,
        unclassifiedIncomingKopecks: 100_000,
        outgoingKopecks: 80_000,
        internalOutgoingKopecks: 0,
      })),
    },
  };
}

describe('подтверждение поступлений от бизнеса', () => {
  it('показывает только полные месяцы, ограничивает суммы и повторяет утверждение с тем же ключом', async () => {
    const user = userEvent.setup();
    let item = document();
    const requests: { body: ConfirmStatementIn; key: string | null }[] = [];
    server.use(http.get('*/api/documents', () => Response.json([item])));
    const original = globalThis.fetch;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/documents/doc-1/confirm')) {
        const body = JSON.parse(init!.body as string) as ConfirmStatementIn;
        requests.push({ body, key: new Headers(init!.headers).get('Idempotency-Key') });
        item = {
          ...item,
          confirmedAt: '2026-10-21T12:05:00Z',
          parsed: {
            ...item.parsed,
            revenueConfirmation: {
              months: Object.fromEntries(
                body.months.map((row) => [row.month, row.businessIncomingKopecks]),
              ),
            },
          },
        };
        if (requests.length === 1) throw new TypeError('lost response after commit');
        return Response.json(item);
      }
      return original(input, init);
    });
    renderWithProviders(<DocumentFiles applicationId="app-1" taskId="task-1" />);
    const field = await screen.findByLabelText(dt.reviewAmount('2026-01'));
    expect(screen.queryByLabelText(dt.reviewAmount('2026-04'))).not.toBeInTheDocument();
    const button = screen.getByRole('button', { name: dt.reviewConfirm });
    expect(button).toBeDisabled();
    await user.clear(field);
    await user.type(field, '1000.01');
    await user.click(screen.getByRole('checkbox', { name: dt.reviewAck }));
    expect(button).toBeDisabled();
    expect(screen.getByText(dt.reviewAmountError)).toBeInTheDocument();
    await user.clear(field);
    await user.type(field, '900,25');
    await user.click(button);
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText(dt.confirmed)).toBeInTheDocument();
    expect(requests).toHaveLength(2);
    expect(requests[0]!.key).toBeTruthy();
    expect(requests[1]!.key).toBe(requests[0]!.key);
    expect(requests[1]!.body).toEqual(requests[0]!.body);
    expect(requests[0]!.body.months[0]!.businessIncomingKopecks).toBe(90_025);
    expect(requests[0]!.body.acknowledged).toBe(true);
    expect(requests[0]!.body.sha256).toBe('a'.repeat(64));
    expect(screen.getByLabelText(dt.reviewAmount('2026-01'))).toHaveValue('900.25');
    expect(screen.getByLabelText(dt.reviewAmount('2026-01'))).toBeDisabled();
  });

  it('даёт использовать выписку из черновика в запросе выручки и блокирует закрытую задачу', async () => {
    const item = { ...document(), taskId: null };
    server.use(http.get('*/api/documents', () => Response.json([item])));
    renderWithProviders(
      <DocumentFiles applicationId="app-1" taskId="task-1" includeUnassignedStatements disabled />,
    );
    expect(await screen.findByRole('link', { name: 'statement.txt' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: dt.reviewAck })).toBeDisabled();
    expect(screen.getByRole('button', { name: dt.reviewConfirm })).toBeDisabled();
  });
});
