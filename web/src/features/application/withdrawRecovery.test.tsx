import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it, vi } from 'vitest';
import { makeApplication, problemResponse } from '@/test/factories';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { applicationPage } from '@/texts';
import { WithdrawButton } from './WithdrawButton';

const t = applicationPage.withdraw;
const application = () =>
  makeApplication({ id: 'withdraw-recovery', status: 'CHECKING', allowedActions: ['WITHDRAW'] });

it('ожидающий отзыв нельзя закрыть Escape или отправить дважды', async () => {
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  server.use(
    http.post('*/api/applications/withdraw-recovery/withdraw', async () => {
      calls += 1;
      await barrier;
      return Response.json({ ...application(), status: 'WITHDRAWN', allowedActions: [] });
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<WithdrawButton application={application()} />);
  try {
    await user.click(screen.getByRole('button', { name: t.action }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.dblClick(dialog.getByRole('button', { name: t.confirm }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(dialog.getByRole('button', { name: t.cancel })).toBeDisabled();
    expect(dialog.queryByRole('button', { name: /Close/ })).not.toBeInTheDocument();
    expect(calls).toBe(1);
  } finally {
    await act(async () => {
      release();
      await barrier;
    });
  }
  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('потерянный ответ: сначала читает состояние, не делает второй отзыв', async () => {
  let posts = 0;
  let reads = 0;
  server.use(
    http.post('*/api/applications/withdraw-recovery/withdraw', () => {
      posts += 1;
      return Response.error();
    }),
    http.get('*/api/applications/withdraw-recovery', () => {
      reads += 1;
      return Response.json({ ...application(), status: 'WITHDRAWN', allowedActions: [] });
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<WithdrawButton application={application()} />);
  await user.click(screen.getByRole('button', { name: t.action }));
  const dialog = within(await screen.findByRole('dialog'));
  await user.click(dialog.getByRole('button', { name: t.confirm }));
  await dialog.findByRole('alert');
  expect(dialog.getByRole('button', { name: t.confirm })).toBeDisabled();
  await user.click(dialog.getByRole('button', { name: t.checkState }));
  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(posts).toBe(1);
  expect(reads).toBe(1);
});

it('сбой чтения сохраняет блокировку, успешная проверка разрешает явный повтор', async () => {
  let posts = 0;
  let reads = 0;
  const keys: (string | null)[] = [];
  server.use(
    http.post('*/api/applications/withdraw-recovery/withdraw', ({ request }) => {
      keys.push(request.headers.get('Idempotency-Key'));
      posts += 1;
      return posts === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json({ ...application(), status: 'WITHDRAWN', allowedActions: [] });
    }),
    http.get('*/api/applications/withdraw-recovery', () => {
      reads += 1;
      return reads === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json(application());
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<WithdrawButton application={application()} />);
  await user.click(screen.getByRole('button', { name: t.action }));
  const dialog = within(await screen.findByRole('dialog'));
  await user.click(dialog.getByRole('button', { name: t.confirm }));
  await dialog.findByRole('alert');
  await user.click(dialog.getByRole('button', { name: t.checkState }));
  await vi.waitFor(() => expect(dialog.getAllByRole('alert')).toHaveLength(2));
  expect(dialog.getByRole('button', { name: t.confirm })).toBeDisabled();
  await user.click(dialog.getByRole('button', { name: t.checkState }));
  await vi.waitFor(() => expect(dialog.getByRole('button', { name: t.confirm })).toBeEnabled());
  await user.click(dialog.getByRole('button', { name: t.confirm }));
  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(posts).toBe(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});
