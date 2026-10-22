import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { describe, expect, it } from 'vitest';
import { sessionQueryKey } from '@/api/session-keys';
import { makeMe, makePublicConfig, problemResponse } from '@/test/factories';
import { createTestQueryClient, renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { errorTexts } from '@/texts';
import { bankLogin } from '@/texts/bank';
import { BankLogin } from './BankLogin';

const BANK_ME = {
  userId: 'bank-user-1',
  displayName: 'Демо-андеррайтер',
  role: 'UNDERWRITER',
  level: 'L2',
};

function Destination() {
  const location = useLocation();
  return <div data-testid="destination">{location.pathname + location.search + location.hash}</div>;
}

function renderLogin(next: string | null = null, queryClient = createTestQueryClient()) {
  return renderWithProviders(
    <MemoryRouter initialEntries={['/login?zone=bank']}>
      <Routes>
        <Route path="/login" element={<BankLogin next={next} />} />
        <Route path="*" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
    queryClient,
  );
}

function enableDemo() {
  server.use(http.get('*/api/public-config', () => Response.json(makePublicConfig())));
}

describe('демо-вход банка', () => {
  it('при выключенном деморежиме объясняет недоступность и не запрашивает вход', async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.post('*/api/auth/bank-demo-login', () => {
        requests += 1;
        return Response.json(BANK_ME);
      }),
    );
    renderLogin();

    expect(await screen.findByText(bankLogin.unavailable)).toBeInTheDocument();
    const button = screen.getByRole('button', { name: bankLogin.submit });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(requests).toBe(0);
    expect(screen.queryByTestId('destination')).not.toBeInTheDocument();
  });

  it('показывает загрузку настроек и позволяет повторить их запрос после ошибки', async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.get('*/api/public-config', () => {
        requests += 1;
        return requests === 1
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : Response.json(makePublicConfig());
      }),
    );
    renderLogin();
    expect(screen.getByRole('status')).toHaveTextContent(bankLogin.checking);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.SERVICE_UNAVAILABLE.text);
    await user.click(within(alert).getByRole('button'));
    expect(await screen.findByRole('button', { name: bankLogin.submit })).toBeEnabled();
    expect(requests).toBe(2);
  });

  it('входит как андеррайтер, обновляет только банковскую сессию и возвращает в банковскую карточку', async () => {
    const user = userEvent.setup();
    const queryClient = createTestQueryClient();
    const client = makeMe();
    const clientData = { application: 'client-application' };
    queryClient.setQueryData(sessionQueryKey('client'), client);
    queryClient.setQueryData(['client-application'], clientData);
    queryClient.setQueryData(sessionQueryKey('bank'), null);
    enableDemo();
    const bodies: unknown[] = [];
    let finishLogin: () => void = () => undefined;
    server.use(
      http.post('*/api/auth/bank-demo-login', async ({ request }) => {
        bodies.push(await request.json());
        return new Promise<Response>((resolve) => {
          finishLogin = () => resolve(Response.json(BANK_ME));
        });
      }),
    );
    renderLogin('/bank/applications/app-1?tab=events#last', queryClient);
    await user.click(await screen.findByRole('button', { name: bankLogin.submit }));
    await waitFor(() => expect(bodies).toEqual([{ role: 'UNDERWRITER' }]));

    const pending = screen.getByRole('button', { name: bankLogin.submitting });
    expect(pending).toBeDisabled();
    await user.click(pending);
    expect(bodies).toHaveLength(1);
    expect(queryClient.getQueryData(sessionQueryKey('bank'))).toBeNull();
    finishLogin();

    expect(await screen.findByTestId('destination')).toHaveTextContent(
      '/bank/applications/app-1?tab=events#last',
    );
    expect(queryClient.getQueryData(sessionQueryKey('bank'))).toEqual({
      ...BANK_ME,
      activeCompanyId: null,
      companies: [],
    });
    expect(queryClient.getQueryState(sessionQueryKey('bank'))?.isInvalidated).toBe(true);
    expect(queryClient.getQueryData(sessionQueryKey('client'))).toEqual(client);
    expect(queryClient.getQueryState(sessionQueryKey('client'))?.isInvalidated).toBe(false);
    expect(queryClient.getQueryData(['client-application'])).toEqual(clientData);
  });

  it.each([
    null,
    '/loans',
    '/banking',
    '//example.test/bank',
    'https://example.test/bank',
    '/bank/../loans',
    '/bank/%2e%2e/loans',
    '/bank\\..\\loans',
    '/\\',
    '/\\[invalid',
  ])('ограничивает адрес возврата банковской зоной: %s', async (next) => {
    const user = userEvent.setup();
    enableDemo();
    server.use(http.post('*/api/auth/bank-demo-login', () => Response.json(BANK_ME)));
    renderLogin(next);
    await user.click(await screen.findByRole('button', { name: bankLogin.submit }));
    expect(await screen.findByTestId('destination')).toHaveTextContent(/^\/bank$/);
  });

  it('сохраняет параметры и якорь очереди банка', async () => {
    const user = userEvent.setup();
    enableDemo();
    server.use(http.post('*/api/auth/bank-demo-login', () => Response.json(BANK_ME)));
    renderLogin('/bank?status=MANUAL_REVIEW#queue');
    await user.click(await screen.findByRole('button', { name: bankLogin.submit }));
    expect(await screen.findByTestId('destination')).toHaveTextContent(
      '/bank?status=MANUAL_REVIEW#queue',
    );
  });

  it('показывает понятную ошибку входа и повторяет запрос из сообщения', async () => {
    const user = userEvent.setup();
    enableDemo();
    let requests = 0;
    server.use(
      http.post('*/api/auth/bank-demo-login', () => {
        requests += 1;
        return requests === 1
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : Response.json(BANK_ME);
      }),
    );
    renderLogin();
    await user.click(await screen.findByRole('button', { name: bankLogin.submit }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.SERVICE_UNAVAILABLE.text);
    expect(alert).not.toHaveTextContent('Служебное описание для разработчика');
    expect(screen.queryByTestId('destination')).not.toBeInTheDocument();
    await user.click(within(alert).getByRole('button'));
    expect(await screen.findByTestId('destination')).toHaveTextContent(/^\/bank$/);
    expect(requests).toBe(2);
  });
});
