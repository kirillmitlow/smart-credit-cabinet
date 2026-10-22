import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it } from 'vitest';
import { makeApplication, makeMe } from '@/test/factories';
import { makeDecision } from '@/test/decisionFactory';
import { testConsents, testContract, testOffer } from '@/test/contractFactory';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { contractTexts as t } from '@/texts/contract';
import { applicationPage } from '@/texts';

it('TS-004: решение → принятие → подпись договора без перезагрузки', async () => {
  mockSessions({ client: makeMe() });
  let status = 'APPROVED';
  let signed = false;
  let acceptCalls = 0;
  let signCalls = 0;
  const contract = () =>
    testContract({
      applicationStatus: status,
      status: signed ? 'SIGNED' : 'READY',
      canSign: !signed,
      progress: { signed: signed ? 1 : 0, required: 1 },
    });
  server.use(
    http.get('*/api/applications/app-1', () =>
      Response.json(
        makeApplication({
          status,
          submittedAt: '2026-10-22T09:00:00Z',
          allowedActions: status === 'APPROVED' ? ['ACCEPT_OFFER', 'WITHDRAW'] : [],
        }),
      ),
    ),
    http.get('*/api/applications/app-1/decision', () => Response.json(makeDecision())),
    http.get('*/api/applications/app-1/offer', () =>
      Response.json(
        testOffer({
          status: 'ACCEPTED',
          contractId: 'contract-1',
        }),
      ),
    ),
    http.get('*/api/contracts/contract-1', () => Response.json(contract())),
    http.get('*/api/applications/app-1/consents', () => Response.json(testConsents())),
    http.post('*/api/offers/offer-1/accept', () => {
      acceptCalls += 1;
      status = 'OFFER_ACCEPTED';
      return Response.json({ applicationStatus: status, offer: testOffer(), contract: contract() });
    }),
    http.post('*/api/contracts/contract-1/sign/request', () =>
      Response.json({
        requestId: 'otp-1',
        expiresInSeconds: 120,
        demoCode: '123456',
      }),
    ),
    http.post('*/api/contracts/contract-1/sign', () => {
      signCalls += 1;
      status = 'SIGNED';
      signed = true;
      return Response.json({ contract: contract(), justSigned: true });
    }),
  );
  renderApp('/applications/app-1');
  await userEvent.click(await screen.findByRole('button', { name: t.accept }));
  await userEvent.click(await screen.findByRole('checkbox', { name: t.agree }));
  await waitFor(() => expect(screen.getByRole('button', { name: t.requestCode })).toBeEnabled());
  await userEvent.click(screen.getByRole('button', { name: t.requestCode }));
  await userEvent.type(await screen.findByRole('textbox', { name: t.code }), '123456');
  await userEvent.click(screen.getByRole('button', { name: t.sign }));
  await screen.findByText(t.signedNotice);
  expect(acceptCalls).toBe(1);
  expect(signCalls).toBe(1);
  expect(
    screen.queryByRole('button', { name: applicationPage.withdraw.decline }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: t.sign })).not.toBeInTheDocument();
});
