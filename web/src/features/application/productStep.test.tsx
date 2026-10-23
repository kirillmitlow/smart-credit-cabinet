import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DocumentOut } from '@/api/generated/model';
import { makeApplication, makeConsents, makeMe } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';

afterEach(() => vi.restoreAllMocks());

function draft() {
  let application = makeApplication();
  const answers: unknown[] = [];
  mockSessions({ client: makeMe() });
  server.use(
    http.get('*/api/applications/app-1', () => Response.json(application)),
    http.get('*/api/applications/app-1/consents', () =>
      Response.json(makeConsents({ allSigned: true })),
    ),
    http.patch('*/api/applications/app-1/draft', async ({ request }) => {
      const body = (await request.json()) as { answers: Record<string, unknown> };
      answers.push(body.answers);
      application = {
        ...application,
        draft: { ...application.draft, ...body.answers },
        version: application.version + 1,
      };
      return Response.json(application);
    }),
  );
  return answers;
}

describe('документы и обеспечение заявки', () => {
  it('не пропускает неполный залог и сохраняет введённую оценку перед следующим шагом', async () => {
    const user = userEvent.setup();
    const answers = draft();
    renderApp('/applications/app-1/edit/3');
    await user.click(await screen.findByLabelText('Предлагаю имущество в залог'));
    expect(screen.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
    await user.type(screen.getByLabelText(/Описание залога/), 'Покупаемая линия оборудования');
    await user.type(screen.getByLabelText(/Ваша оценка стоимости/), '25000000');
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));
    await screen.findByRole('heading', { level: 1, name: /Шаг 4 из 5/ });
    expect(answers).toContainEqual({
      collateral: { description: 'Покупаемая линия оборудования', valueRub: 25_000_000 },
    });
  });

  it('передаёт multipart с исходным файлом и показывает сохранённый файл', async () => {
    const user = userEvent.setup();
    draft();
    let files: DocumentOut[] = [];
    let received: FormData | undefined;
    let key: string | null = null;
    server.use(http.get('*/api/documents', () => Response.json(files)));
    const originalFetch = globalThis.fetch;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/documents') && init?.method === 'POST') {
        received = init.body as FormData;
        key = new Headers(init.headers).get('Idempotency-Key');
        const saved: DocumentOut = {
          id: 'document-1',
          companyId: 'company-1',
          applicationId: 'app-1',
          taskId: null,
          kind: 'OTHER',
          origin: 'UPLOADED',
          filename: 'contract.pdf',
          mime: 'application/pdf',
          sizeBytes: 20,
          sha256: 'a'.repeat(64),
          parseStatus: 'NOT_REQUIRED',
          parsed: null,
          parseError: null,
          createdAt: '2026-10-21T12:00:00Z',
          cancelledAt: null,
          confirmedAt: null,
        };
        files = [saved];
        return Response.json(saved, { status: 201 });
      }
      return originalFetch(input, init);
    });
    const { container } = renderApp('/applications/app-1/edit/3');
    await screen.findByLabelText('Прикрепить документ');
    await user.upload(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      new File(['%PDF-1.4\ntest'], 'contract.pdf', {
        type: 'application/pdf',
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Загрузить файл' }));
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'contract.pdf' })).toHaveAttribute(
        'href',
        '/api/documents/document-1/download?preview=true',
      ),
    );
    expect(received?.get('applicationId')).toBe('app-1');
    expect(received?.get('kind')).toBe('OTHER');
    expect((received?.get('file') as File).name).toBe('contract.pdf');
    expect(key).toBeTruthy();
  });
});
