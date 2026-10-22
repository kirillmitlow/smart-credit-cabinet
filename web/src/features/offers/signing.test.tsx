import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { getGetApplicationQueryKey, type getApplicationResponse } from '@/api/generated/api';
import type { ContractOut } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeApplication, problemResponse } from '@/test/factories';
import { createTestQueryClient, renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { contractTexts as t } from '@/texts/contract';
import { ContractCodeForm } from './ContractCodeForm';
import { ContractSigning } from './ContractSigning';
import { OfferActions } from './OfferActions';
import { testConsents, testContract, testOffer } from '@/test/contractFactory';

function serve(initial = testContract(), pepAccepted = true) {
  let current = initial;
  server.use(
    http.get('*/api/applications/app-1/offer', () =>
      Response.json(
        testOffer({
          status: 'ACCEPTED',
          contractId: current.id,
        }),
      ),
    ),
    http.get('*/api/contracts/contract-1', () => Response.json(current)),
    http.get('*/api/applications/app-1/consents', () => Response.json(testConsents(pepAccepted))),
    http.post('*/api/contracts/contract-1/sign/request', () =>
      Response.json({
        requestId: 'otp-1',
        expiresInSeconds: 120,
        demoCode: '123456',
      }),
    ),
  );
  return {
    set: (value: Partial<ContractOut>) => {
      current = { ...current, ...value };
    },
  };
}

describe('принятие предложения', () => {
  it('двойной клик принимает один вариант и обновляет статус заявки', async () => {
    const calls: { key: string | null; body: unknown }[] = [];
    server.use(
      http.post('*/api/offers/offer-1/accept', async ({ request }) => {
        calls.push({ key: request.headers.get('Idempotency-Key'), body: await request.json() });
        await delay(30);
        return Response.json({
          applicationStatus: 'OFFER_ACCEPTED',
          offer: testOffer(),
          contract: testContract(),
        });
      }),
    );
    const client = createTestQueryClient();
    client.setQueryData<getApplicationResponse>(getGetApplicationQueryKey('app-1'), {
      data: makeApplication({ status: 'APPROVED', allowedActions: ['WITHDRAW'] }),
      status: 200,
      headers: new Headers(),
    });
    renderWithProviders(<OfferActions offer={testOffer()} variantId="variant-1" />, client);
    await userEvent.dblClick(screen.getByRole('button', { name: t.accept }));
    await screen.findByText(t.accepted);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.key).toBeTruthy();
    expect(calls[0]?.body).toEqual({ variantId: 'variant-1' });
    const cached = client.getQueryData<getApplicationResponse>(getGetApplicationQueryKey('app-1'));
    expect(cached?.status === 200 && cached.data.status).toBe('OFFER_ACCEPTED');
    expect(cached?.status === 200 && cached.data.allowedActions).toEqual([]);
  });

  it('повтор после сбоя сохраняет ключ действия', async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/api/offers/offer-1/accept', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        return keys.length === 1
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : Response.json({
              applicationStatus: 'OFFER_ACCEPTED',
              offer: testOffer(),
              contract: testContract(),
            });
      }),
    );
    renderWithProviders(<OfferActions offer={testOffer()} />);
    await userEvent.click(screen.getByRole('button', { name: t.accept }));
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: t.accept }));
    await screen.findByText(t.accepted);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('варианты ещё готовятся: принять нельзя', () => {
    renderWithProviders(<OfferActions offer={testOffer({ variantsStatus: 'PENDING' })} />);
    expect(screen.getByRole('button', { name: t.accept })).toBeDisabled();
  });
});

describe('договор и подпись', () => {
  it('показывает условия договора и доступный документ, без автоматической галочки', async () => {
    serve();
    const { container } = renderWithProviders(<ContractSigning applicationId="app-1" />);
    await screen.findByRole('heading', { name: t.heading });
    expect(screen.getByText(/500\s000\s₽/)).toBeInTheDocument();
    expect(screen.getByText('21,5%')).toBeInTheDocument();
    expect(screen.getByText(/46\s677\s₽/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t.document })).toHaveAttribute(
      'href',
      '/api/contracts/contract-1/document',
    );
    expect(screen.getByRole('checkbox', { name: t.agree })).not.toBeChecked();
    expect(screen.getByRole('button', { name: t.requestCode })).toBeDisabled();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('галочка и правила ПЭП обязательны, открывать документ не требуется', async () => {
    serve(testContract(), false);
    const bodies: unknown[] = [];
    server.use(
      http.post('*/api/contracts/contract-1/sign/request', async ({ request }) => {
        bodies.push(await request.json());
        return Response.json({ requestId: 'otp-1', expiresInSeconds: 120, demoCode: '123456' });
      }),
    );
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await userEvent.click(await screen.findByRole('checkbox', { name: t.agree }));
    expect(screen.getByRole('button', { name: t.requestCode })).toBeDisabled();
    await userEvent.click(await screen.findByRole('checkbox', { name: t.acceptPep }));
    await userEvent.click(screen.getByRole('button', { name: t.requestCode }));
    await screen.findByRole('textbox', { name: t.code });
    expect(bodies).toEqual([{ agree: true, acceptPepRules: true }]);
  });

  it('подпись кодом отправляется один раз, после неё виден статус выдачи', async () => {
    const api = serve();
    let calls = 0;
    server.use(
      http.post('*/api/contracts/contract-1/sign', async ({ request }) => {
        calls += 1;
        expect(await request.json()).toEqual({ requestId: 'otp-1', code: '123456' });
        api.set({
          status: 'SIGNED',
          applicationStatus: 'SIGNED',
          canSign: false,
          progress: { signed: 1, required: 1 },
        });
        await delay(25);
        return Response.json({
          contract: testContract({
            status: 'SIGNED',
            applicationStatus: 'SIGNED',
            canSign: false,
            progress: { signed: 1, required: 1 },
          }),
          justSigned: true,
        });
      }),
    );
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await userEvent.click(await screen.findByRole('checkbox', { name: t.agree }));
    await waitFor(() => expect(screen.getByRole('button', { name: t.requestCode })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: t.requestCode }));
    await userEvent.type(await screen.findByRole('textbox', { name: t.code }), '123456');
    await userEvent.dblClick(screen.getByRole('button', { name: t.sign }));
    await screen.findByText(t.signedNotice);
    expect(calls).toBe(1);
    expect(screen.queryByRole('button', { name: t.sign })).not.toBeInTheDocument();
  });

  it('сотрудник передаёт директору и не видит форму подписи', async () => {
    serve(testContract({ canSign: false, canPassToDirector: true }));
    let calls = 0;
    server.use(
      http.post('*/api/contracts/contract-1/request-signature', async () => {
        calls += 1;
        await delay(25);
        return Response.json({
          contractId: 'contract-1',
          requestedAt: '2026-10-22T09:00:00Z',
          repeated: false,
        });
      }),
    );
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await userEvent.dblClick(await screen.findByRole('button', { name: t.pass }));
    await screen.findByText(t.passed);
    expect(calls).toBe(1);
    expect(screen.queryByRole('checkbox', { name: t.agree })).not.toBeInTheDocument();
  });

  it('изменившиеся права после ROLE_CANNOT_SIGN перечитываются: появляется передача директору', async () => {
    const api = serve();
    server.use(
      http.post('*/api/contracts/contract-1/sign/request', () => {
        api.set({ canSign: false, canPassToDirector: true });
        return problemResponse({ status: 403, code: 'ROLE_CANNOT_SIGN' });
      }),
    );
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await userEvent.click(await screen.findByRole('checkbox', { name: t.agree }));
    await waitFor(() => expect(screen.getByRole('button', { name: t.requestCode })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: t.requestCode }));
    await screen.findByRole('button', { name: t.pass });
    expect(screen.queryByRole('button', { name: t.requestCode })).not.toBeInTheDocument();
  });

  it('линия показывает лимит без обещания фиксированного платежа', async () => {
    serve(testContract({ productCode: 'CREDIT_LINE' }));
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await screen.findByText(t.limit);
    expect(screen.queryByText(t.payment)).not.toBeInTheDocument();
  });

  it.each([
    ['DISBURSING', t.issuing],
    ['DISBURSED', t.issued],
  ])('показывает подтверждённый сервером статус %s', async (status, text) => {
    serve(testContract({ status: 'SIGNED', applicationStatus: status, canSign: false }));
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await screen.findByText(text);
  });

  it('ошибка загрузки показывает повтор и затем восстанавливает договор', async () => {
    serve();
    let fail = true;
    server.use(
      http.get('*/api/contracts/contract-1', () =>
        fail
          ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
          : Response.json(testContract()),
      ),
    );
    renderWithProviders(<ContractSigning applicationId="app-1" />);
    await screen.findByRole('alert');
    fail = false;
    await userEvent.click(screen.getByRole('button'));
    await screen.findByRole('heading', { name: t.heading });
  });
});

describe('ошибки кода подписи', () => {
  it('три неверных кода блокируют подпись', async () => {
    server.use(
      http.post('*/api/contracts/contract-1/sign', () =>
        problemResponse({ status: 422, code: 'CODE_INVALID' }),
      ),
    );
    renderWithProviders(
      <ContractCodeForm
        contractId="contract-1"
        challenge={{ requestId: 'otp-1', expiresInSeconds: 120 }}
        issuedAt={Date.now()}
        onSigned={vi.fn()}
        onNewCode={vi.fn()}
        requesting={false}
      />,
    );
    for (let i = 0; i < 3; i += 1) {
      await userEvent.type(screen.getByRole('textbox', { name: t.code }), '000000');
      await userEvent.click(screen.getByRole('button', { name: t.sign }));
      await waitFor(() => expect(screen.getByRole('textbox', { name: t.code })).toHaveValue(''));
    }
    expect(await screen.findByText(t.blocked)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t.sign })).not.toBeInTheDocument();
  });

  it('истечение срока не отправляет код и предлагает получить новый', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    try {
      renderWithProviders(
        <ContractCodeForm
          contractId="contract-1"
          challenge={{ requestId: 'otp-1', expiresInSeconds: 1 }}
          issuedAt={Date.now()}
          onSigned={vi.fn()}
          onNewCode={vi.fn()}
          requesting={false}
        />,
      );
      act(() => {
        vi.advanceTimersByTime(1_001);
      });
      expect(screen.getByText(t.expired)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: t.newCode })).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: t.code })).toBeDisabled();
    } finally {
      vi.useRealTimers();
    }
  });
});
