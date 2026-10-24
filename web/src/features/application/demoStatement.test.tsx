import { http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DocumentOut } from '@/api/generated/model';
import { renderWithProviders } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { problemResponse } from '@/test/factories';
import { server } from '@/test/server';
import { documentTexts as dt } from '@/texts/documents';
import { DocumentFiles } from './DocumentFiles';

const generated: DocumentOut = {
  id: 'demo-file',
  companyId: 'company-1',
  applicationId: 'app-1',
  taskId: 'task-1',
  kind: 'BANK_STATEMENT_1C',
  origin: 'DEMO_GENERATED',
  filename: 'statement.txt',
  mime: 'text/plain; charset=windows-1251',
  sizeBytes: 100,
  sha256: 'a'.repeat(64),
  parseStatus: 'PENDING',
  parsed: null,
  parseError: null,
  createdAt: '2026-10-21T12:00:00Z',
  cancelledAt: null,
  confirmedAt: null,
};

describe('демо-выписка для запроса выручки', () => {
  it.each([
    { demoMode: false, allow: true, taskId: 'task-1' },
    { demoMode: true, allow: false, taskId: 'task-1' },
    { demoMode: true, allow: true, taskId: undefined },
  ])(
    'скрывает генерацию без демо, запроса выручки или задачи: %j',
    async ({ demoMode, allow, taskId }) => {
      mockSessions({ config: { demoMode } });
      renderWithProviders(
        <DocumentFiles applicationId="app-1" taskId={taskId} allowDemoStatement={allow} />,
      );
      await screen.findByRole('button', { name: dt.upload });
      await waitFor(() => expect(screen.queryByLabelText(dt.loading)).not.toBeInTheDocument());
      expect(screen.queryByRole('button', { name: dt.generateStatement })).not.toBeInTheDocument();
    },
  );

  it('после потерянного ответа повторяет тот же ключ, сохраняет синтетическое происхождение и ждёт разбор', async () => {
    mockSessions({ config: { demoMode: true } });
    const user = userEvent.setup();
    let files: DocumentOut[] = [];
    const keys: (string | null)[] = [];
    const received = vi.fn();
    server.use(
      http.get('*/api/documents', () => Response.json(files)),
      http.post('*/api/demo/bank-statement', async ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        expect(await request.json()).toEqual({ applicationId: 'app-1', taskId: 'task-1' });
        if (keys.length === 1) return Response.error();
        files = [generated];
        return Response.json(generated, { status: 201 });
      }),
    );
    renderWithProviders(
      <DocumentFiles
        applicationId="app-1"
        taskId="task-1"
        allowDemoStatement
        onUploaded={received}
      />,
    );
    const button = await screen.findByRole('button', { name: dt.generateStatement });
    await user.click(button);
    await screen.findByRole('alert');
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText(dt.demoGenerated)).toBeInTheDocument();
    expect(screen.getByText(dt.pending)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: dt.reviewConfirm })).not.toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    expect(received).toHaveBeenCalledWith(generated);
  });

  it('при недоступном генераторе показывает понятную ошибку и сохраняет ручную загрузку', async () => {
    mockSessions({ config: { demoMode: true } });
    server.use(
      http.post('*/api/demo/bank-statement', () =>
        problemResponse({
          status: 503,
          code: 'DEMO_STATEMENT_UNAVAILABLE',
        }),
      ),
    );
    const { container } = renderWithProviders(
      <DocumentFiles applicationId="app-1" taskId="task-1" allowDemoStatement />,
    );
    await userEvent.click(await screen.findByRole('button', { name: dt.generateStatement }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Генератор тестовой выписки недоступен',
    );
    expect(container.querySelector('input[type="file"]')).toBeEnabled();
  });
});
