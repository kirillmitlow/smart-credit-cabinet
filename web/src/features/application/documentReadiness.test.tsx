import { http } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import type { DocumentOut } from '@/api/generated/model';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { makeApplication, makeMe } from '@/test/factories';
import { makeTask, makeTaskList } from '@/test/tasksFactory';
import { clientTasks as t } from '@/texts';
import { documentTexts as dt } from '@/texts/documents';

it('T-424: текст не разрешает отправку неподтверждённой выписки; подтверждение обновляет готовность без перезагрузки', async () => {
  mockSessions({ client: makeMe() });
  let confirmed = false;
  let reads = 0;
  const file = (): DocumentOut => ({
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
    cancelledAt: null,
    confirmedAt: confirmed ? '2026-10-21T12:05:00Z' : null,
    createdAt: '2026-10-21T12:00:00Z',
    parsed: {
      months: ['2026-01', '2026-02', '2026-03'].map((month) => ({
        month,
        complete: true,
        unclassifiedIncomingKopecks: 100_000,
        outgoingKopecks: 80_000,
        internalOutgoingKopecks: 0,
      })),
    },
  });
  server.use(
    http.get('*/api/applications/app-1', () =>
      Response.json(
        makeApplication({
          status: 'NEEDS_INFO',
          allowedActions: ['RESPOND'],
        }),
      ),
    ),
    http.get('*/api/applications/app-1/tasks', () => {
      reads += 1;
      return Response.json(
        makeTaskList([
          makeTask({
            draftAnswer: 'Проверил выписку',
            documentReady: confirmed,
          }),
        ]),
      );
    }),
    http.get('*/api/documents', () => Response.json([file()])),
    http.post('*/api/documents/doc-1/confirm', () => {
      confirmed = true;
      return Response.json(file());
    }),
  );
  renderApp('/applications/app-1');
  expect(await screen.findByRole('button', { name: t.submit })).toBeDisabled();
  expect(screen.getByText(dt.documentsNotReady)).toBeInTheDocument();
  const before = reads;
  const user = userEvent.setup();
  await user.click(await screen.findByRole('checkbox', { name: dt.reviewAck }));
  await user.click(screen.getByRole('button', { name: dt.reviewConfirm }));
  await waitFor(() => expect(screen.getByRole('button', { name: t.submit })).toBeEnabled());
  expect(reads).toBeGreaterThan(before);
  expect(screen.queryByText(dt.documentsNotReady)).not.toBeInTheDocument();
});
