import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it, vi } from 'vitest';
import type { PaymentRequest, ProductOut } from '@/api/generated/model';
import { formatMoney } from '@/lib/format';
import { blockingA11yViolations } from '@/test/a11y';
import { makeMe, problemResponse } from '@/test/factories';
import { makePayment } from '@/test/paymentFactory';
import { renderApp, renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { catalogTexts as t, guards, productNames, variantCard } from '@/texts';
import { ProductCalculator } from './ProductCalculator';

const plainMoney = (value: number) => formatMoney(value).replaceAll('\u00a0', ' ');
function product(
  code: keyof typeof productNames = 'EXPRESS',
  overrides: Partial<ProductOut> = {},
): ProductOut {
  return {
    code,
    title: productNames[code],
    purpose: 'Финансирование бизнеса',
    repayment: 'ANNUITY',
    amountMinRub: 100_000,
    amountMaxRub: 10_000_000,
    termMinMonths: 1,
    termMaxMonths: 60,
    collateralRequiredAboveRub: null,
    ratePercentFrom: 21.5,
    autoDecisionMode: 'ALWAYS',
    autoDecisionUpToRub: null,
    requiresBankCustomer: false,
    requiresContract: false,
    documents: ['Документы компании'],
    available: true,
    unavailableReasons: [],
    hint: null,
    requiresSecurity: false,
    ...overrides,
  };
}
function catalog(items: ProductOut[]) {
  mockSessions({ client: makeMe() });
  server.use(http.get('*/api/products', () => Response.json({ items })));
}

it('TS-083: шесть продуктов, причины недоступности и переход к расчёту без барьеров доступности', async () => {
  catalog(
    Object.keys(productNames).map((code) =>
      product(
        code as keyof typeof productNames,
        code === 'OVERDRAFT'
          ? {
              available: false,
              unavailableReasons: [
                {
                  code: 'TOO_EARLY',
                  text: 'Нужна история счёта',
                  action: 'Продолжайте пользоваться счётом',
                  availableFrom: '2027-04-22',
                },
              ],
            }
          : {},
      ),
    ),
  );
  const user = userEvent.setup();
  const { container } = renderApp('/products');
  await screen.findByRole('heading', { level: 2, name: productNames.EXPRESS });
  expect(screen.getAllByRole('article')).toHaveLength(6);
  expect(screen.getByText('Нужна история счёта')).toBeInTheDocument();
  expect(screen.getByText('Продолжайте пользоваться счётом')).toBeInTheDocument();
  expect(screen.getByText(/22 апреля 2027/)).toBeInTheDocument();
  expect(await blockingA11yViolations(container)).toEqual([]);
  await user.click(screen.getAllByRole('link', { name: t.details })[0]!);
  await screen.findByRole('heading', { level: 1, name: productNames.EXPRESS });
  await screen.findByText(plainMoney(47_280));
  expect(screen.getByRole('slider', { name: t.amountSlider })).toBeInTheDocument();
  expect(screen.getByRole('slider', { name: t.termSlider })).toBeInTheDocument();
  expect(await blockingA11yViolations(container)).toEqual([]);
});

it('серверная ошибка каталога допускает повтор без вымышленных продуктов', async () => {
  mockSessions({ client: makeMe() });
  let calls = 0;
  server.use(
    http.get('*/api/products', () =>
      ++calls === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json({ items: [product()] }),
    ),
  );
  const user = userEvent.setup();
  renderApp('/products');
  await screen.findByRole('heading', { name: t.failed });
  expect(screen.queryByText(productNames.EXPRESS)).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Повторить/ }));
  await screen.findByRole('heading', { level: 2, name: productNames.EXPRESS });
});

it.each(['/products/UNKNOWN', '/products/overdraft'])(
  'неизвестный адрес %s не запрашивает каталог',
  async (path) => {
    mockSessions({ client: makeMe() });
    let calls = 0;
    server.use(
      http.get('*/api/products', () => {
        calls++;
        return Response.json({ items: [] });
      }),
    );
    renderApp(path);
    await screen.findByRole('heading', { name: guards.pageNotFound.title });
    expect(calls).toBe(0);
  },
);

it('каталог недоступен поручителю, запрос за него не выполняется', async () => {
  mockSessions({ client: makeMe({ role: 'GUARANTOR' }) });
  let calls = 0;
  server.use(
    http.get('*/api/products', () => {
      calls++;
      return Response.json({ items: [] });
    }),
  );
  renderApp('/products');
  await screen.findByRole('heading', { name: guards.pageNotFound.title });
  expect(calls).toBe(0);
});

it('показывает ответ API, скрывает старые числа при вводе; неверная сумма не отправляется', async () => {
  const requests: PaymentRequest[] = [];
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) => {
      const body = (await request.json()) as PaymentRequest;
      requests.push(body);
      return Response.json(
        makePayment(body, { paymentRub: body.amountRub === 500_000 ? 12_345 : 23_456 }),
      );
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<ProductCalculator product={product()} />);
  await screen.findByText(plainMoney(12_345));
  const amount = screen.getByRole('textbox', { name: t.amount });
  await user.clear(amount);
  expect(screen.queryByText(plainMoney(12_345))).not.toBeInTheDocument();
  await user.type(amount, '20');
  await new Promise((resolve) => setTimeout(resolve, 300));
  expect(requests).toHaveLength(1);
  expect(screen.queryByText(plainMoney(12_345))).not.toBeInTheDocument();
  await user.clear(amount);
  await user.type(amount, '650000');
  await screen.findByText(plainMoney(23_456));
  expect(requests).toEqual([
    { productCode: 'EXPRESS', amountRub: 500_000, termMonths: 12 },
    { productCode: 'EXPRESS', amountRub: 650_000, termMonths: 12 },
  ]);
});

it('ввод срока вне границ тоже выключает запрос и прежний результат', async () => {
  const received = vi.fn();
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) => {
      const body = (await request.json()) as PaymentRequest;
      received(body);
      return Response.json(makePayment(body));
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<ProductCalculator product={product()} />);
  await screen.findByText(plainMoney(47_280));
  const term = screen.getByRole('textbox', { name: t.term });
  await user.clear(term);
  await user.type(term, '99');
  await new Promise((resolve) => setTimeout(resolve, 300));
  expect(received).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(plainMoney(47_280))).not.toBeInTheDocument();
});

it.each(['BULLET', 'LINE', 'OVERDRAFT'])(
  '%s: проценты и возврат долга не названы аннуитетом',
  async (repayment) => {
    server.use(
      http.post('*/api/calculator/payment', async ({ request }) =>
        Response.json(
          makePayment((await request.json()) as PaymentRequest, {
            paymentKind: 'INTEREST_ONLY',
            paymentRub: 8_750,
            lastPaymentRub: 508_750,
            overpaymentRub: 105_000,
          }),
        ),
      ),
    );
    renderWithProviders(<ProductCalculator product={product('CREDIT_LINE', { repayment })} />);
    await screen.findByText(plainMoney(8_750));
    const card = screen.getByTestId('variant-card');
    expect(card).toHaveTextContent(variantCard.paymentInterestOnly);
    if (repayment === 'BULLET') {
      expect(await screen.findByText(/Последний платёж:/)).toHaveTextContent(plainMoney(508_750));
    } else {
      expect(screen.getByText(t.revolving)).toBeInTheDocument();
      expect(screen.getByText(/Проценты за выбранный срок:/)).toHaveTextContent(
        plainMoney(105_000),
      );
      expect(within(card).queryByText(/Переплата/)).not.toBeInTheDocument();
    }
  },
);

it('ошибка калькулятора допускает повтор, не подменяется локальной формулой', async () => {
  let calls = 0;
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) =>
      ++calls === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json(
            makePayment((await request.json()) as PaymentRequest, { paymentRub: 33_333 }),
          ),
    ),
  );
  const user = userEvent.setup();
  renderWithProviders(<ProductCalculator product={product()} />);
  await screen.findByRole('alert');
  expect(screen.queryByText(plainMoney(47_280))).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Повторить/ }));
  await screen.findByText(plainMoney(33_333));
  await waitFor(() => expect(calls).toBe(2));
});
