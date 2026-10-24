import { useState } from 'react';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, it, vi } from 'vitest';
import type { PaymentRequest } from '@/api/generated/model';
import { problemResponse } from '@/test/factories';
import { makePayment } from '@/test/paymentFactory';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { applicationForm } from '@/texts';
import { formatMoney } from '@/lib/format';
import { PaymentEstimate } from './PaymentEstimate';

const t = applicationForm.conditions;
const moneyLabel = (amount: number) => formatMoney(amount).replaceAll('\u00a0', ' ');

it('форма и сводка показывают серверный ответ, не вычисляя платёж по ставке браузера', async () => {
  let calls = 0;
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) => {
      calls += 1;
      const body = (await request.json()) as PaymentRequest;
      expect(body).toEqual({ productCode: 'EXPRESS', amountRub: 500000, termMonths: 12 });
      return Response.json(makePayment(body, { paymentRub: 12_345 }));
    }),
  );
  renderWithProviders(
    <>
      <PaymentEstimate productCode="EXPRESS" amountRub={500000} termMonths={12} />
      <PaymentEstimate compact productCode="EXPRESS" amountRub={500000} termMonths={12} />
    </>,
  );
  for (const id of ['payment', 'payment-review']) {
    expect(await within(screen.getByTestId(id)).findByText(moneyLabel(12_345))).toBeInTheDocument();
  }
  expect(calls).toBe(1);
});

it('смена суммы сразу скрывает прежний ответ, завершение старого запроса не подменяет новый', async () => {
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  let oldStarted = false;
  let oldFinished = false;
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) => {
      const body = (await request.json()) as PaymentRequest;
      if (body.amountRub === 500000) {
        oldStarted = true;
        await barrier;
        oldFinished = true;
      }
      return Response.json(
        makePayment(body, { paymentRub: body.amountRub === 500000 ? 11111 : 22222 }),
      );
    }),
  );
  function Harness() {
    const [amount, setAmount] = useState(500000);
    return (
      <>
        <button onClick={() => setAmount(600000)}>Change</button>
        <PaymentEstimate productCode="EXPRESS" amountRub={amount} termMonths={12} />
      </>
    );
  }
  const user = userEvent.setup();
  renderWithProviders(<Harness />);
  try {
    await vi.waitFor(() => expect(oldStarted).toBe(true));
    await user.click(screen.getByRole('button', { name: 'Change' }));
    expect(screen.queryByText(moneyLabel(11111))).not.toBeInTheDocument();
    expect(await screen.findByText(moneyLabel(22222))).toBeInTheDocument();
  } finally {
    release();
    await vi.waitFor(() => expect(oldFinished).toBe(true));
  }
  expect(screen.queryByText(moneyLabel(11111))).not.toBeInTheDocument();
});

it('ошибка не подставляет локальную сумму, есть повтор; неподдержанный/неполный ввод не отправляется', async () => {
  let calls = 0;
  server.use(
    http.post('*/api/calculator/payment', async ({ request }) => {
      calls += 1;
      return calls === 1
        ? problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })
        : Response.json(
            makePayment((await request.json()) as PaymentRequest, { paymentRub: 33333 }),
          );
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <PaymentEstimate productCode="EXPRESS" amountRub={500000} termMonths={12} />
      <PaymentEstimate productCode="OVERDRAFT" amountRub={500000} termMonths={12} />
      <PaymentEstimate productCode="EXPRESS" amountRub="" termMonths={12} />
    </>,
  );
  expect(await screen.findByText(t.paymentFailed)).toBeInTheDocument();
  expect(calls).toBe(1);
  await user.click(screen.getByRole('button', { name: t.paymentRetry }));
  expect(await screen.findByText(moneyLabel(33333))).toBeInTheDocument();
  expect(calls).toBe(2);
});
