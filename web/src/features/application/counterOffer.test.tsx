import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { ClientDecisionOut } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { testConsents, testContract, testOffer } from '@/test/contractFactory';
import { makeCounterDecision, snabkontraktVariants } from '@/test/counterOfferFactory';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { applicationPage, counterOffer as t, decision, errorTexts } from '@/texts';
import { contractTexts } from '@/texts/contract';
import { forbiddenClientWords } from '@/texts/forbidden';

function show(data: ClientDecisionOut, allowedActions = ['ACCEPT_OFFER', 'WITHDRAW']) {
  let status = 'COUNTER_OFFER';
  mockSessions({ client: makeMe() });
  server.use(
    http.get('*/api/applications/app-1', () =>
      Response.json(
        makeApplication({
          status,
          amountRub: 8_000_000,
          termMonths: 12,
          productCode: 'WORKING_CAPITAL',
          submittedAt: '2026-10-21T09:04:00Z',
          allowedActions: status === 'COUNTER_OFFER' ? allowedActions : [],
        }),
      ),
    ),
    http.get('*/api/applications/app-1/decision', () => Response.json(data)),
    // после принятия страница показывает подпись договора, как у одобрения
    http.get('*/api/applications/app-1/offer', () =>
      Response.json(testOffer({ status: 'ACCEPTED', contractId: 'contract-1' })),
    ),
    http.get('*/api/contracts/contract-1', () => Response.json(testContract())),
    http.get('*/api/applications/app-1/consents', () => Response.json(testConsents(true))),
  );
  return {
    ...renderApp('/applications/app-1'),
    accepted: () => {
      status = 'OFFER_ACCEPTED';
    },
  };
}

async function cards() {
  await screen.findByRole('group', { name: t.cardsLabel });
  return screen.getAllByTestId('variant-card');
}

describe('T-423: встречное предложение, три карточки', () => {
  it('СнабКонтракт: три карточки по 30-17, одна с «Рекомендуем»', async () => {
    const { container } = show(makeCounterDecision());
    const [longer, less, contract] = await cards();
    expect(screen.getAllByTestId('variant-card')).toHaveLength(3);
    expect(screen.getAllByText('Рекомендуем')).toHaveLength(1);

    expect(longer).toHaveTextContent('Рекомендуем');
    expect(longer).toHaveTextContent(/8.000.000.₽/);
    expect(longer).toHaveTextContent(/36.месяцев/);
    expect(longer).toHaveTextContent('19,5%');
    expect(longer).not.toHaveTextContent('от 19,5%');
    expect(longer).toHaveTextContent(/295.274.₽/);
    expect(longer).toHaveTextContent('Сумма как вы просили, срок дольше');
    expect(longer).toHaveTextContent(`${t.changed.term}: 12 месяцев → 36 месяцев`);
    expect(longer).toHaveTextContent(t.needsNothing);

    expect(less).not.toHaveTextContent('Рекомендуем');
    expect(less).toHaveTextContent(/3.400.000.₽/);
    expect(less).toHaveTextContent(/12.месяцев/);
    expect(less).toHaveTextContent(/314.144.₽/);

    expect(contract).toHaveTextContent(/130.000.₽/);
    expect(contract).toHaveTextContent('только проценты');
    expect(contract).toHaveTextContent(
      `${t.changed.product}: Оборотный кредит → Кредит под контракт`,
    );
    expect(contract).toHaveTextContent(t.needsHeading);
    expect(contract).toHaveTextContent('Подтвердить контракт № 17');

    for (const card of [longer!, less!, contract!]) {
      expect(within(card).getByText('Почему подходит вам', { exact: false })).toBeInTheDocument();
      expect(within(card).getByRole('button', { name: t.choose })).toBeEnabled();
    }
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('«Как получить то, что просили»: запрос, что мешает и что можно сделать', async () => {
    show(makeCounterDecision());
    await cards();
    const block = screen.getByTestId('how-to-block');
    expect(within(block).getByRole('heading', { name: t.how.heading })).toBeInTheDocument();
    expect(block).toHaveTextContent(/Вы просили 8.000.000.₽ на 12.месяцев/);
    expect(block).toHaveTextContent('Платёж по запрошенным условиям слишком велик для выручки');
    expect(block).toHaveTextContent('Рассмотрите больший срок или меньшую сумму');
  });

  it('выбор карточки: одно принятие с variantId и ключом, дальше подпись договора', async () => {
    const user = userEvent.setup();
    const calls: { key: string | null; body: unknown }[] = [];
    const view = show(makeCounterDecision());
    server.use(
      http.post('*/api/offers/offer-1/accept', async ({ request }) => {
        calls.push({ key: request.headers.get('Idempotency-Key'), body: await request.json() });
        await delay(200);
        view.accepted();
        return Response.json({
          applicationStatus: 'OFFER_ACCEPTED',
          offer: testOffer({ status: 'ACCEPTED', contractId: 'contract-1' }),
          contract: testContract(),
        });
      }),
    );
    const [, less] = await cards();
    const choose = within(less!).getByRole('button', { name: t.choose });
    await user.dblClick(choose);
    // пока идёт запрос, остальные карточки не нажимаются
    await waitFor(() => {
      expect(
        within(screen.getAllByTestId('variant-card')[0]!).getByRole('button', { name: t.choose }),
      ).toBeDisabled();
    });
    expect(await screen.findByText(contractTexts.heading)).toBeVisible();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.key).toBeTruthy();
    expect(calls[0]?.body).toEqual({ variantId: 'variant-less' });
    expect(screen.queryByTestId('variant-card')).not.toBeInTheDocument();
  });

  it('карточка с залогом: 409 SECURITY_REQUIRED показывается текстом, остальные карточки доступны', async () => {
    const user = userEvent.setup();
    const variants = snabkontraktVariants();
    variants[2] = {
      ...variants[2]!,
      collateralRequired: true,
      whatChanged: { security: true },
    };
    show(makeCounterDecision({}, variants));
    server.use(
      http.post('*/api/offers/offer-1/accept', () =>
        problemResponse({
          status: 409,
          code: 'SECURITY_REQUIRED',
          errors: [{ field: 'variantId', message: 'variant-contract' }],
        }),
      ),
    );
    const all = await cards();
    // «что нужно от вас» честно говорит про залог ещё до нажатия
    expect(all[2]).toHaveTextContent(t.needsSecurity);
    await user.click(within(all[2]!).getByRole('button', { name: t.choose }));
    const alert = await within(all[2]!).findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.SECURITY_REQUIRED.text);
    expect(alert).not.toHaveTextContent('SECURITY_REQUIRED');
    expect(within(all[0]!).getByRole('button', { name: t.choose })).toBeEnabled();
  });

  it('варианты ещё не готовы (PENDING): карточек и выбора нет, есть обновление', async () => {
    const user = userEvent.setup();
    const data = makeCounterDecision();
    if (data.offer) {
      data.offer.variantsStatus = 'PENDING';
      data.offer.variants = [];
    }
    show(data);
    expect(await screen.findByText(t.pending)).toBeVisible();
    expect(screen.queryByTestId('variant-card')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: t.choose })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: decision.refresh })).toBeEnabled();
    // блок «как получить» остаётся: причины от этого не зависят
    expect(screen.getByTestId('how-to-block')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: decision.refresh }));
  });

  it('нет права принять: карточки видны, кнопок выбора нет', async () => {
    show(makeCounterDecision(), ['WITHDRAW']);
    await cards();
    expect(screen.queryByRole('button', { name: t.choose })).not.toBeInTheDocument();
  });

  it('нет причин от сервера: блока «как получить» нет, ничего не выдумываем', async () => {
    show(makeCounterDecision({ reasons: [], whatAffected: [], nextSteps: [] }));
    await cards();
    expect(screen.queryByTestId('how-to-block')).not.toBeInTheDocument();
  });

  it('«Отказаться» остаётся на странице', async () => {
    show(makeCounterDecision());
    await cards();
    expect(
      screen.getByRole('button', { name: applicationPage.withdraw.decline }),
    ).toBeInTheDocument();
  });

  it('клиенту не показываются внутренние слова и коды', async () => {
    show(makeCounterDecision());
    await cards();
    const text = document.body.textContent ?? '';
    for (const { pattern } of forbiddenClientWords) expect(text).not.toMatch(pattern);
    expect(text).not.toMatch(
      /DSCR_LOW|LONGER_TERM|LESS_AMOUNT|OTHER_PRODUCT|WORKING_CAPITAL|CONTRACT\b/,
    );
    expect(text).not.toMatch(/баллы|score/i);
  });
});
