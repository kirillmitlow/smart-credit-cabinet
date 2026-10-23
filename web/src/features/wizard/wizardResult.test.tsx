import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import { NBSP, formatMoney } from '@/lib/format';
import { blockingA11yViolations } from '@/test/a11y';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp, renderAppWithState } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import {
  makeLineRecommended,
  makeRecommended,
  makeRejected,
  makeWizardResult,
} from '@/test/wizardFactory';
import { errorTexts, termHints, variantCard, wizard, wizardResult } from '@/texts';
import type { ResultLocationState } from './wizardModel';

/** jest-dom сводит неразрывные пробелы к обычным только в тексте элемента, поэтому ожидание приводим так же */
const plain = (text: string) => text.replaceAll(NBSP, ' ');

const alternative = makeRecommended({
  productCode: 'WORKING_CAPITAL',
  title: 'Оборотный кредит',
  why: 'Закупка товара или сырья',
  paymentRub: 51_000,
  ratePercentFrom: 21,
  decisionTime: 'MANUAL',
  documents: ['Выписка из другого банка'],
  comfortableOptions: [],
});

function resultState(overrides: Partial<ResultLocationState> = {}): ResultLocationState {
  return {
    answers: { purpose: 'GOODS', amountRub: 500_000, termMonths: 12 },
    applicationId: 'draft-1',
    result: makeWizardResult({ alternative }),
    ...overrides,
  };
}

function openResult(state: ResultLocationState = resultState()) {
  mockSessions({ client: makeMe() });
  return renderAppWithState('/wizard/result', state);
}

describe('результат подбора: карточки', () => {
  it('основной вариант с меткой, альтернатива без неё; числа как у бэкенда', async () => {
    const { container } = openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const cards = screen.getAllByTestId('variant-card');
    expect(cards).toHaveLength(2);

    const primary = within(cards[0] as HTMLElement);
    expect(primary.getByRole('heading', { level: 3, name: 'Экспресс-кредит' })).toBeInTheDocument();
    expect(primary.getByText(variantCard.recommendedBadge)).toBeInTheDocument();
    expect(primary.getByText(/Небольшая сумма на оборудование/)).toBeInTheDocument();
    expect(cards[0]).toHaveTextContent(plain(formatMoney(500_000)));
    expect(cards[0]).toHaveTextContent('12 месяцев');
    expect(cards[0]).toHaveTextContent(plain(formatMoney(46_677)));
    // переплата выбранного срока приходит из вариантов платежа бэкенда
    expect(cards[0]).toHaveTextContent(plain(formatMoney(60_124)));
    expect(cards[0]).toHaveTextContent('от 24% в год');
    expect(cards[0]).toHaveTextContent(variantCard.rateApproximate);
    expect(cards[0]).toHaveTextContent(variantCard.decisionAuto);
    // другие сроки, кроме выбранного
    const other = within(primary.getByTestId('comfortable-options'));
    expect(other.getAllByRole('listitem')).toHaveLength(2);
    expect(other.getByText(/24 месяца/)).toHaveTextContent(variantCard.fits);

    const second = within(cards[1] as HTMLElement);
    expect(second.queryByText(variantCard.recommendedBadge)).not.toBeInTheDocument();
    expect(second.getByRole('heading', { level: 3, name: 'Оборотный кредит' })).toBeInTheDocument();
    expect(cards[1]).toHaveTextContent(variantCard.decisionManual);
    expect(cards[1]).toHaveTextContent('Выписка из другого банка');
    expect(cards[1]).toHaveTextContent(plain(formatMoney(51_000)));

    expect(screen.getByRole('button', { name: wizardResult.changeAnswers })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: wizardResult.openCatalog })).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('слова-термины с подсказкой: платёж, переплата, ставка', async () => {
    openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = within(screen.getAllByTestId('variant-card')[0] as HTMLElement);
    expect(card.getByRole('button', { name: variantCard.payment })).toBeInTheDocument();
    expect(card.getByRole('button', { name: termHints.overpayment.term })).toBeInTheDocument();
    expect(card.getByRole('button', { name: termHints.rate.term })).toBeInTheDocument();
  });

  it('сумма не названа: платёж откладывается, цифры не выдумываем', async () => {
    openResult(
      resultState({
        answers: { purpose: 'EQUIPMENT', amountRub: null },
        result: makeWizardResult({
          primary: makeRecommended({ paymentRub: null, paymentKind: null, comfortableOptions: [] }),
        }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = screen.getByTestId('variant-card');
    expect(card).toHaveTextContent(variantCard.paymentLater);
    expect(card).not.toHaveTextContent(variantCard.amount);
  });

  it('линия: платёж только по процентам названа прямо', async () => {
    openResult(
      resultState({
        answers: { purpose: 'GOODS', amountRub: 1_000_000 },
        result: makeWizardResult({ primary: makeLineRecommended() }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    expect(screen.getByTestId('variant-card')).toHaveTextContent(variantCard.paymentInterestOnly);
  });

  it('путь «На запуск»: объяснение про поручительство и залог, ручное рассмотрение', async () => {
    openResult(
      resultState({
        result: makeWizardResult({
          ruleId: 'START_PATH',
          startPath: true,
          primary: makeRecommended({
            requiresSecurity: true,
            decisionTime: 'MANUAL',
            why: 'Бизнесу до 6 месяцев кредит доступен с поручительством владельца или залогом',
          }),
        }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const startPath = screen.getByTestId('start-path');
    expect(startPath).toHaveTextContent(wizardResult.startPath.heading);
    expect(startPath).toHaveTextContent(/Поручительство — обещание владельца/);
    const card = screen.getByTestId('variant-card');
    expect(card).toHaveTextContent(variantCard.needsSecurity);
    expect(card).toHaveTextContent(variantCard.decisionManual);
  });

  it('залог и контракт названы в карточке', async () => {
    openResult(
      resultState({
        result: makeWizardResult({
          primary: makeRecommended({ needsCollateral: true, needsContract: true }),
        }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = screen.getByTestId('variant-card');
    expect(card).toHaveTextContent(variantCard.needsCollateral);
    expect(card).toHaveTextContent(variantCard.needsContract);
  });

  it('недоступный продукт показан с причиной, шагом и датой; будущая подсказка отдельно', async () => {
    openResult(
      resultState({
        result: makeWizardResult({
          alternative: null,
          rejected: [makeRejected()],
          hint: 'Овердрафт станет доступен через 6 месяцев',
        }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const rejected = screen.getByTestId('rejected-candidate');
    expect(rejected).toHaveTextContent('Овердрафт');
    expect(rejected).toHaveTextContent('Овердрафт доступен клиентам банка');
    expect(rejected).toHaveTextContent('Откройте счёт у нас');
    expect(rejected).toHaveTextContent('Станет доступно 22 апреля 2027');
    expect(screen.getByTestId('future-hint')).toHaveTextContent(
      'Овердрафт станет доступен через 6 месяцев',
    );
    expect(screen.getAllByTestId('variant-card')).toHaveLength(1);
    expect(screen.getByText(wizardResult.introSingle)).toBeInTheDocument();
    expect(screen.queryByText(wizardResult.intro)).not.toBeInTheDocument();
  });

  it('подходящего нет: «что станет доступно», каталог и «Изменить ответы»', async () => {
    const { container } = openResult(
      resultState({
        result: makeWizardResult({
          outcome: 'CATALOG_HINT',
          primary: null,
          hint: 'По этим условиям подходящих продуктов нет',
          rejected: [makeRejected()],
        }),
      }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.noneTitle });
    expect(screen.queryByTestId('variant-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('catalog-hint')).toHaveTextContent('подходящих продуктов нет');
    expect(screen.queryByRole('link', { name: wizardResult.openCatalog })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: wizardResult.changeAnswers })).toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('без ответов (прямой заход): предлагаем начать подбор', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/wizard/result');
    await screen.findByRole('heading', { level: 1, name: wizardResult.noAnswers });
    expect(screen.getByRole('link', { name: wizardResult.startAgain })).toHaveAttribute(
      'href',
      '/wizard',
    );
  });
});

describe('результат подбора: оформление заявки', () => {
  it('основной вариант: черновик уже заполнен мастером, открываем шаг «Условия»', async () => {
    const user = userEvent.setup();
    let patches = 0;
    server.use(
      http.get('*/api/applications/draft-1', () =>
        Response.json(makeApplication({ id: 'draft-1', productCode: 'EXPRESS' })),
      ),
      http.patch('*/api/applications/draft-1/draft', () => {
        patches += 1;
        return Response.json(makeApplication({ id: 'draft-1' }));
      }),
    );
    openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = within(screen.getAllByTestId('variant-card')[0] as HTMLElement);
    await user.click(card.getByRole('button', { name: wizardResult.apply }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5: Условия/ }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/applications/draft-1/edit/1');
    expect(patches).toBe(0);
  });

  it('запасной вариант: продукт в черновике меняется на выбранный, сумма и срок остаются', async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    let current = makeApplication({ id: 'draft-1', productCode: 'EXPRESS', version: 3 });
    server.use(
      http.get('*/api/applications/draft-1', () => Response.json(current)),
      http.patch('*/api/applications/draft-1/draft', async ({ request }) => {
        const body = (await request.json()) as { productCode: string; version: number };
        patches.push(body);
        current = { ...current, productCode: body.productCode, version: body.version + 1 };
        return Response.json(current);
      }),
    );
    openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = within(screen.getAllByTestId('variant-card')[1] as HTMLElement);
    await user.click(card.getByRole('button', { name: wizardResult.apply }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5: Условия/ }),
    ).toBeInTheDocument();
    expect(patches).toEqual([
      {
        version: 3,
        productCode: 'WORKING_CAPITAL',
        amountRub: 500_000,
        termMonths: 12,
        answers: {},
      },
    ]);
    expect(window.location.pathname).toBe('/applications/draft-1/edit/1');
  });

  it('черновика нет: создаём заявку и сразу кладём в неё продукт, сумму и срок', async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    let created = 0;
    const draft = makeApplication({ id: 'fresh-1', productCode: null, amountRub: null });
    server.use(
      http.post('*/api/applications', () => {
        created += 1;
        return Response.json(draft, { status: 201 });
      }),
      http.patch('*/api/applications/fresh-1/draft', async ({ request }) => {
        patches.push(await request.json());
        return Response.json({ ...draft, productCode: 'EXPRESS', version: 2 });
      }),
      http.get('*/api/applications/fresh-1', () =>
        Response.json({ ...draft, productCode: 'EXPRESS', version: 2 }),
      ),
    );
    openResult(
      resultState({ applicationId: null, result: makeWizardResult({ applicationId: null }) }),
    );
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    await user.click(screen.getByRole('button', { name: wizardResult.apply }));
    expect(
      await screen.findByRole('heading', { level: 1, name: /Шаг 1 из 5: Условия/ }),
    ).toBeInTheDocument();
    expect(created).toBe(1);
    expect(patches).toEqual([
      {
        version: draft.version,
        productCode: 'EXPRESS',
        amountRub: 500_000,
        termMonths: 12,
        answers: {},
      },
    ]);
    expect(window.location.pathname).toBe('/applications/fresh-1/edit/1');
  });

  it('заявку не удалось подготовить: понятная ошибка, остаёмся на результате', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('*/api/applications/draft-1', () =>
        Response.json(makeApplication({ id: 'draft-1', version: 3 })),
      ),
      http.patch('*/api/applications/draft-1/draft', () =>
        problemResponse({ status: 409, code: 'VERSION_CONFLICT', requestId: 'req-conflict' }),
      ),
    );
    openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    const card = within(screen.getAllByTestId('variant-card')[1] as HTMLElement);
    await user.click(card.getByRole('button', { name: wizardResult.apply }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.VERSION_CONFLICT.text);
    expect(alert).toHaveTextContent('req-conflict');
    expect(window.location.pathname).toBe('/wizard/result');
  });

  it('«Изменить ответы» возвращает в мастер с прежними ответами', async () => {
    const user = userEvent.setup();
    openResult();
    await screen.findByRole('heading', { level: 1, name: wizardResult.title });
    await user.click(screen.getByRole('button', { name: wizardResult.changeAnswers }));
    await screen.findByRole('heading', { level: 1, name: wizard.purpose.title });
    expect(window.location.pathname).toBe('/wizard');
    expect(screen.getByText(wizard.restored)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: new RegExp(wizard.purpose.options.GOODS.title) }),
    ).toHaveAttribute('aria-pressed', 'true');
  });
});
