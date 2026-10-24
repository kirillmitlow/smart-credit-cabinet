import { http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DocumentOut } from '@/api/generated/model';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { documentTexts as dt } from '@/texts/documents';
import { DocumentFiles } from './DocumentFiles';

function statement(changes: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: 'doc-1',
    companyId: 'company-1',
    applicationId: 'app-1',
    taskId: 'task-1',
    kind: 'BANK_STATEMENT_1C',
    origin: 'UPLOADED',
    filename: 'statement.txt',
    mime: 'text/plain',
    sizeBytes: 100,
    sha256: 'a'.repeat(64),
    parseStatus: 'PENDING',
    parsed: null,
    parseError: null,
    createdAt: '2026-10-21T12:00:00Z',
    cancelledAt: null,
    confirmedAt: null,
    ...changes,
  };
}

describe('разбор и замена выписки', () => {
  it('обновляет ожидание до результата, показывает период и отделяет поступления от выручки', async () => {
    let reads = 0;
    server.use(
      http.get('*/api/documents', () =>
        Response.json([
          statement(
            ++reads === 1
              ? {}
              : {
                  parseStatus: 'PARSED',
                  parsed: {
                    period: { start: '2026-01-01', end: '2026-03-31' },
                    requiresReview: true,
                  },
                },
          ),
        ]),
      ),
    );
    renderWithProviders(<DocumentFiles applicationId="app-1" taskId="task-1" />);
    expect(await screen.findByText(dt.pending)).toBeInTheDocument();
    expect(await screen.findByText(dt.parsed, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(dt.period('2026-01-01', '2026-03-31'))).toBeInTheDocument();
    expect(screen.getByText(dt.parsedHelp)).toBeInTheDocument();
    expect(screen.queryByText(dt.pending)).not.toBeInTheDocument();
  });

  it('сохраняет вид и цель замены, исходный файл и ключ повтора при потерянном ответе', async () => {
    const user = userEvent.setup();
    let files = [statement({ parseStatus: 'FAILED', parseError: 'INN_MISMATCH' })];
    const requests: { body: FormData; key: string | null }[] = [];
    server.use(http.get('*/api/documents', () => Response.json(files)));
    const originalFetch = globalThis.fetch;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/documents') && init?.method === 'POST') {
        requests.push({
          body: init.body as FormData,
          key: new Headers(init.headers).get('Idempotency-Key'),
        });
        if (requests.length === 1) throw new TypeError('lost response');
        const saved = statement({ id: 'doc-2', filename: 'replacement.txt' });
        files = [{ ...files[0]!, cancelledAt: '2026-10-21T12:02:00Z' }, saved];
        return Response.json(saved, { status: 201 });
      }
      return originalFetch(input, init);
    });
    const { container } = renderWithProviders(
      <DocumentFiles applicationId="app-1" taskId="task-1" />,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(dt.parseErrors.INN_MISMATCH!);
    await user.click(screen.getByRole('button', { name: `${dt.replace}: statement.txt` }));
    await user.upload(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      new File(['1CClientBankExchange'], 'replacement.txt', { type: 'text/plain' }),
    );
    await user.click(screen.getByRole('button', { name: dt.upload }));
    await waitFor(() => expect(screen.getByRole('button', { name: dt.upload })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: dt.upload }));
    expect(await screen.findByRole('link', { name: 'replacement.txt' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'statement.txt' })).not.toBeInTheDocument();
    expect(requests).toHaveLength(2);
    expect(requests[0]!.key).toBeTruthy();
    expect(requests[1]!.key).toBe(requests[0]!.key);
    for (const { body } of requests) {
      expect(body.get('replacesId')).toBe('doc-1');
      expect(body.get('taskId')).toBe('task-1');
      expect(body.get('kind')).toBe('BANK_STATEMENT_1C');
    }
  });

  it('не предлагает замену при закрытой задаче, неизвестная ошибка имеет понятный запасной текст', async () => {
    server.use(
      http.get('*/api/documents', () =>
        Response.json([statement({ parseStatus: 'FAILED', parseError: 'NEW_ERROR_CODE' })]),
      ),
    );
    renderWithProviders(<DocumentFiles applicationId="app-1" taskId="task-1" disabled />);
    expect(await screen.findByRole('alert')).toHaveTextContent(dt.parseFailed);
    expect(screen.getByRole('button', { name: `${dt.replace}: statement.txt` })).toBeDisabled();
  });
});
