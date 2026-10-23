import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { WizardRequest, WizardResult } from '@/api/generated/model';
import { NBSP, formatMoney } from '@/lib/format';
import { blockingA11yViolations } from '@/test/a11y';
import { makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import {
  defaultOptions,
  makeLineRecommended,
  makeRecommended,
  makeRejected,
  makeWizardResult,
} from '@/test/wizardFactory';
import { applicationForm, errorTexts, wizard, wizardResult } from '@/texts';

type Responder = (body: WizardRequest, call: number) => WizardResult | Response;

/** Сервер подбора: запоминает тела запросов, отвечает так, как решит тест */
function mockRecommend(responder: Responder) {
  const bodies: WizardRequest[] = [];
  server.use(
    http.post('*/api/wizard/recommendations', async ({ request }) => {
      const body = (await request.json()) as WizardRequest;
      bodies.push(body);
      const answer = responder(body, bodies.length);
      return answer instanceof Response ? answer : Response.json(answer);
    }),
  );
  return { bodies };
}

/** jest-dom сводит неразрывные пробелы к обычным только в тексте элемента, поэтому ожидание приводим так же */
const plain = (text: string) => text.replaceAll(NBSP, ' ');

const choice = (name: string | RegExp) => screen.getByRole('button', { name });
const heading = (name: string | RegExp) => screen.findByRole('heading', { level: 1, name });

async function openWizard() {
  mockSessions({ client: makeMe() });
  const view = renderApp('/wizard');
  await heading(wizard.purpose.title);
  return view;
}

describe('мастер подбора: первый вопрос', () => {
  it('шесть карточек, «Не знаю», прогресс, фокус на заголовке, доступность', async () => {
    const { container } = await openWizard();
    const title = screen.getByRole('heading', { level: 1, name: wizard.purpose.title });
    expect(title).toHaveFocus();
    for (const option of Object.values(wizard.purpose.options)) {
      expect(choice(new RegExp(option.title))).toBeInTheDocument();
    }
    expect(choice(wizard.unknown)).toBeInTheDocument();
    expect(screen.getByText('Шаг 1 из 4')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: wizard.back })).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('проходится клавиатурой: Tab до карточки, Enter, фокус на новом заголовке', async () => {
    const user = userEvent.setup();
    await openWizard();
    await user.tab();
    expect(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title))).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(await heading(wizard.amount.title)).toHaveFocus();
  });
});

describe('мастер подбора: ветвление и запросы', () => {
  it('оборудование на небольшую сумму: платёж и залог не спрашиваем, запрос один', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() =>
      makeWizardResult({
        primary: makeRecommended({ comfortableOptions: [] }),
        askCollateral: false,
      }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '1500000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizardResult.title);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toEqual({
      answers: { purpose: 'EQUIPMENT', amountRub: 1_500_000 },
      applicationId: null,
    });
    expect(window.location.pathname).toBe('/wizard/result');
    expect(screen.queryByText(wizard.collateral.title)).not.toBeInTheDocument();
  });

  it('заказ с оплатой позже: регулярность, срок, госзаказ, сумма, платёж; черновик переиспользуется', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend((_body, call) =>
      makeWizardResult({
        ruleId: 'ORDER_GOV',
        primary: makeRecommended({
          productCode: 'WORKING_CAPITAL',
          title: 'Оборотный кредит',
          comfortableOptions: defaultOptions,
        }),
        applicationId: call === 1 ? 'draft-77' : 'draft-77',
      }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.ORDER.title)));

    await heading(wizard.frequency.title);
    expect(screen.getByText('Шаг 2 из 7')).toBeInTheDocument();
    await user.click(choice(new RegExp(wizard.frequency.options.ONCE.title)));

    await heading(wizard.payback.title);
    await user.click(choice(wizard.payback.options.MONTHS_1_3.title));

    await heading(wizard.govContract.title);
    await user.click(choice(wizard.govContract.options.YES.title));

    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '4000000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));

    await heading(wizard.payment.title);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]?.answers).toEqual({
      purpose: 'ORDER',
      frequency: 'ONCE',
      paybackHorizon: 'MONTHS_1_3',
      govContract: 'YES',
      amountRub: 4_000_000,
    });
    // Варианты платежа приходят из ответа бэкенда, на фронте ничего не считается
    const fitting = screen.getByRole('button', { name: new RegExp(wizard.payment.fits) });
    expect(fitting).toHaveTextContent('24 месяца');
    expect(fitting).toHaveTextContent(plain(formatMoney(25_500)));
    expect(fitting).toHaveTextContent(plain(formatMoney(112_000)));
    await user.click(fitting);

    await heading(wizardResult.title);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual({
      answers: { ...bodies[0]?.answers, termMonths: 24 },
      applicationId: 'draft-77',
    });
  });

  it('залог спрашиваем, когда бэкенд сказал: сумма выше порога', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() =>
      makeWizardResult({
        ruleId: 'EQUIPMENT_LARGE',
        primary: makeRecommended({
          productCode: 'INVESTMENT',
          title: 'Инвестиционный кредит',
          needsCollateral: true,
        }),
        askCollateral: true,
      }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '12000000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));

    await heading(wizard.payment.title);
    await user.click(choice(wizard.payment.unknown));

    await heading(wizard.collateral.title);
    expect(screen.getByRole('button', { name: 'Залог' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: wizard.unknown })).not.toBeInTheDocument();
    await user.click(choice(new RegExp(wizard.collateral.options.PURCHASED_ITEM.title)));

    await heading(wizardResult.title);
    expect(bodies).toHaveLength(2);
    expect(bodies[0]?.answers).toEqual({ purpose: 'EQUIPMENT', amountRub: 12_000_000 });
    expect(bodies[1]?.answers).toEqual({
      purpose: 'EQUIPMENT',
      amountRub: 12_000_000,
      termMonths: null,
      collateral: 'PURCHASED_ITEM',
    });
  });

  it('у продукта без платежа по сроку вопроса «комфортный платёж» нет', async () => {
    const user = userEvent.setup();
    mockRecommend(() =>
      makeWizardResult({
        ruleId: 'GOODS_REGULAR',
        primary: makeLineRecommended(),
      }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.GOODS.title)));
    await heading(wizard.frequency.title);
    await user.click(choice(new RegExp(wizard.frequency.options.REGULAR.title)));
    await heading(wizard.payback.title);
    await user.click(choice(wizard.payback.options.WEEKS.title));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '2000000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizardResult.title);
    expect(screen.queryByText(wizard.payment.title)).not.toBeInTheDocument();
  });

  it('нехватка денег: вопрос про срок звучит «На сколько не хватает?»', async () => {
    const user = userEvent.setup();
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.GAP.title)));
    await heading(wizard.frequency.title);
    await user.click(choice(new RegExp(wizard.frequency.options.ONCE.title)));
    await heading(wizard.payback.titleGap);
  });

  it('«Не знаю» на каждом вопросе не блокирует: в запрос уходит UNKNOWN', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() =>
      makeWizardResult({
        outcome: 'CATALOG_HINT',
        primary: null,
        ruleId: null,
        hint: 'Расскажите, на что нужны деньги, или выберите продукт в каталоге',
        applicationId: 'draft-1',
      }),
    );
    await openWizard();
    await user.click(choice(wizard.unknown));
    await heading(wizard.amount.title);
    await user.click(choice(wizard.unknown));
    expect(screen.getByText(wizard.amount.help.body)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: wizard.amount.help.skip }));
    await heading(wizardResult.noneTitle);
    expect(bodies[0]?.answers).toEqual({ purpose: 'UNKNOWN', amountRub: null });
  });

  it('«Не знаю» про регулярность, срок возврата и госзаказ', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() => makeWizardResult({ primary: makeLineRecommended() }));
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.ORDER.title)));
    await heading(wizard.frequency.title);
    await user.click(choice(wizard.unknown));
    await heading(wizard.payback.title);
    await user.click(choice(wizard.unknown));
    await heading(wizard.govContract.title);
    await user.click(choice(wizard.unknown));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '300000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizardResult.title);
    expect(bodies[0]?.answers).toEqual({
      purpose: 'ORDER',
      frequency: 'UNKNOWN',
      paybackHorizon: 'UNKNOWN',
      govContract: 'UNKNOWN',
      amountRub: 300_000,
    });
  });

  it('«Назад» помнит выбор; смена цели убирает ненужные вопросы и ответы', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() =>
      makeWizardResult({ primary: makeRecommended({ comfortableOptions: [] }) }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.GOODS.title)));
    await heading(wizard.frequency.title);
    await user.click(choice(new RegExp(wizard.frequency.options.REGULAR.title)));
    await heading(wizard.payback.title);

    await user.click(screen.getByRole('button', { name: wizard.back }));
    await heading(wizard.frequency.title);
    expect(choice(new RegExp(wizard.frequency.options.REGULAR.title))).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await user.click(screen.getByRole('button', { name: wizard.back }));
    await heading(wizard.purpose.title);
    expect(choice(new RegExp(wizard.purpose.options.GOODS.title))).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    // Другая цель: вопросов про регулярность и срок возврата нет, старые ответы в запрос не уходят
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '900000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizardResult.title);
    expect(bodies[0]?.answers).toEqual({ purpose: 'EQUIPMENT', amountRub: 900_000 });
  });

  it('с платежа можно вернуться к сумме: она на месте, а выбранный срок сбрасывается', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() => makeWizardResult());
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '1000000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizard.payment.title);
    await user.click(screen.getByRole('button', { name: wizard.back }));
    await heading(wizard.amount.title);
    const field = screen.getByLabelText(/Сумма/);
    expect(field).toHaveValue(`1${' '}000${' '}000`);
    await user.clear(field);
    await user.type(field, '2000000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));
    await heading(wizard.payment.title);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]?.answers).toEqual({ purpose: 'EQUIPMENT', amountRub: 2_000_000 });
    expect(bodies[1]?.applicationId).toBe('draft-1');
  });
});

describe('мастер подбора: сумма и ошибки', () => {
  it('пустая, нулевая и слишком большая сумма: понятные ошибки, запросов нет', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend(() => makeWizardResult());
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    const submit = () => user.click(screen.getByRole('button', { name: wizard.amount.next }));

    await submit();
    expect(await screen.findByText(applicationForm.validation.amountRequired)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Сумма/), '0');
    await submit();
    expect(await screen.findByText(applicationForm.validation.amountInvalid)).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/Сумма/));
    await user.type(screen.getByLabelText(/Сумма/), '2000000000');
    await submit();
    expect(await screen.findByText(applicationForm.validation.amountTooBig)).toBeInTheDocument();
    expect(bodies).toHaveLength(0);
  });

  it('ошибка api: текст по коду, «Повторить» отправляет тот же запрос', async () => {
    const user = userEvent.setup();
    const { bodies } = mockRecommend((_body, call) =>
      call === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE', requestId: 'req-wiz' })
        : makeWizardResult({ primary: makeRecommended({ comfortableOptions: [] }) }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.EQUIPMENT.title)));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '500000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(errorTexts.SERVICE_UNAVAILABLE.text);
    expect(alert).toHaveTextContent('req-wiz');
    // остаёмся на вопросе, ответ не потерян
    expect(
      screen.getByRole('heading', { level: 1, name: wizard.amount.title }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Сумма/)).toHaveValue('500 000');

    await user.click(screen.getByRole('button', { name: errorTexts.SERVICE_UNAVAILABLE.action }));
    await heading(wizardResult.title);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
  });
});

describe('результат: подбор без вариантов и недоступные продукты', () => {
  it('«каталог с подсказкой» не тупик: причина, отклонённые кандидаты, переход в каталог', async () => {
    const user = userEvent.setup();
    mockRecommend(() =>
      makeWizardResult({
        outcome: 'CATALOG_HINT',
        primary: null,
        hint: 'Овердрафт станет доступен после 6 месяцев обслуживания у нас',
        rejected: [makeRejected()],
      }),
    );
    await openWizard();
    await user.click(choice(new RegExp(wizard.purpose.options.GAP.title)));
    await heading(wizard.frequency.title);
    await user.click(choice(new RegExp(wizard.frequency.options.ONCE.title)));
    await heading(wizard.payback.titleGap);
    await user.click(choice(wizard.payback.options.DAYS.title));
    await heading(wizard.amount.title);
    await user.type(screen.getByLabelText(/Сумма/), '200000');
    await user.click(screen.getByRole('button', { name: wizard.amount.next }));

    await heading(wizardResult.noneTitle);
    const hint = screen.getByTestId('catalog-hint');
    expect(hint).toHaveTextContent('Овердрафт станет доступен после 6 месяцев');
    expect(hint).toHaveTextContent(wizardResult.noneNext);
    const rejected = screen.getByTestId('rejected-candidate');
    expect(rejected).toHaveTextContent('Овердрафт');
    expect(rejected).toHaveTextContent('Откройте счёт у нас');
    expect(rejected).toHaveTextContent('Станет доступно 22 апреля 2027');
    expect(screen.queryByRole('link', { name: wizardResult.openCatalog })).not.toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe('/wizard/result'));
  });
});
