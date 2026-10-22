import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it } from 'vitest';
import { sessionQueryKey } from '@/api/session-keys';
import { makeMe, problemResponse } from '@/test/factories';
import { createTestQueryClient, renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { placeholders } from '@/texts';
import { bankLogin } from '@/texts/bank';

it('после входа с прежним bank=null открывает зону банка и сохраняет клиентскую сессию', async () => {
  const user = userEvent.setup();
  const client = makeMe({ displayName: 'Клиентская вкладка' });
  const bank = { userId: 'bank-1', displayName: 'Андеррайтер', role: 'UNDERWRITER', level: 'L2' };
  let signedIn = false;
  mockSessions({ client, config: { demoMode: true } });
  server.use(
    http.post('*/api/auth/bank-demo-login', () => {
      signedIn = true;
      return Response.json(bank);
    }),
    http.get('*/api/auth/bank-me', () =>
      signedIn ? Response.json(bank) : problemResponse({ status: 401, code: 'UNAUTHENTICATED' }),
    ),
  );
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(sessionQueryKey('bank'), null);
  queryClient.setQueryData(sessionQueryKey('client'), client);
  renderApp('/login?zone=bank', queryClient);
  await user.click(await screen.findByRole('button', { name: bankLogin.submit }));
  expect(
    await screen.findByRole('heading', { name: placeholders.bankQueue.title }),
  ).toBeInTheDocument();
  expect(window.location.pathname).toBe('/bank');
  expect(queryClient.getQueryData(sessionQueryKey('client'))).toEqual(client);
  expect(queryClient.getQueryData(sessionQueryKey('bank'))).toMatchObject(bank);
});
