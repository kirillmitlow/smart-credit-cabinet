import { useState } from 'react';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/render';
import { problemResponse } from '@/test/factories';
import { server } from '@/test/server';
import { request } from './client';
import { useActionKey } from './idempotency';

/** Кнопка «Отправить заявку»: ключ создаётся на действие, после успеха сбрасывается */
function SubmitButton() {
  const action = useActionKey();
  const [status, setStatus] = useState('idle');
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setStatus('sending');
          request('/api/v1/applications/1/submit', { method: 'POST', ...action.request() })
            .then(() => {
              action.reset();
              setStatus('done');
            })
            .catch(() => setStatus('failed'));
        }}
      >
        send
      </button>
      <output>{status}</output>
    </>
  );
}

describe('useActionKey', () => {
  it('двойной клик отправляет один и тот же Idempotency-Key', async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/api/v1/applications/1/submit', async ({ request: req }) => {
        keys.push(req.headers.get('Idempotency-Key'));
        await delay(100); // оба нажатия приходятся на время выполнения первого запроса
        return HttpResponse.json({ status: 'SUBMITTED' });
      }),
    );
    renderWithProviders(<SubmitButton />);
    const user = userEvent.setup();
    await user.dblClick(screen.getByRole('button', { name: 'send' }));
    await waitFor(() => expect(keys.length).toBeGreaterThanOrEqual(2));
    expect(new Set(keys).size).toBe(1);
    expect(keys[0]).toBeTruthy();
  });

  it('повтор после сбоя сохраняет ключ, после успеха ключ новый', async () => {
    const keys: string[] = [];
    let fail = true;
    server.use(
      http.post('*/api/v1/applications/1/submit', ({ request: req }) => {
        keys.push(req.headers.get('Idempotency-Key') ?? '');
        return fail
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : HttpResponse.json({ status: 'SUBMITTED' });
      }),
    );
    renderWithProviders(<SubmitButton />);
    const user = userEvent.setup();
    const button = screen.getByRole('button', { name: 'send' });

    await user.click(button);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('failed'));

    fail = false;
    await user.click(button);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('done'));
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);

    // следующее действие пользователя — новый ключ
    await user.click(button);
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[2]).not.toBe(keys[0]);
  });
});
