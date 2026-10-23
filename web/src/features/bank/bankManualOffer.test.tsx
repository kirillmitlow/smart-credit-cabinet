import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { BankOfferEvaluation } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeBankCard, makeBankDecision } from '@/test/bankFactory';
import { makeBankMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { bankActions as t, bankManual as m } from '@/texts/bankActions';

function evaluation(changes: Partial<BankOfferEvaluation> = {}): BankOfferEvaluation {
  return {
    applicationId: 'bank-app',
    version: 3,
    engineDecisionId: 'engine',
    allowed: true,
    evaluationRef: 'checked-terms',
    requiredLevel: 'L1',
    minCommentChars: 20,
    deviation: true,
    exceptionUsed: false,
    ratePercent: 19.5,
    corridorMinPercent: 15,
    corridorMaxPercent: 30,
    paymentRub: 123456,
    lastPaymentRub: 120000,
    overpaymentRub: 500000,
    dscr: 2.345,
    stressDscr: 1.876,
    violations: [],
    ...changes,
  };
}

async function setup(level: 'L1' | 'L2' = 'L2', requiredLevel = 'L1') {
  mockSessions({ bank: makeBankMe('UNDERWRITER', { level }) });
  server.use(
    http.get('*/api/backoffice/applications/:id', () =>
      Response.json(makeBankCard({ decision: makeBankDecision({ requiredLevel }) })),
    ),
  );
  renderApp('/bank/applications/bank-app?expectedVersion=3');
  await userEvent.click(await screen.findByRole('button', { name: t.manual }));
  return screen.findByRole('dialog');
}

async function ready(dialog: HTMLElement) {
  const amount = within(dialog).getByLabelText(m.amount);
  await userEvent.clear(amount);
  await userEvent.type(amount, '10000000');
  await userEvent.selectOptions(within(dialog).getByLabelText(t.reason), 'UW_RISK_HIGHER');
  await userEvent.type(
    within(dialog).getByLabelText(t.comment),
    'Риск по документам требует уменьшить сумму',
  );
}

describe('ручные условия банка (T-433)', () => {
  it('показывает только серверный расчёт и сохраняет ссылку вместо пересчёта условий клиентом', async () => {
    const previews: unknown[] = [];
    const saves: unknown[] = [];
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', async ({ request }) => {
        previews.push(await request.json());
        return Response.json(evaluation());
      }),
      http.post('*/api/backoffice/applications/:id/decision', async ({ request }) => {
        saves.push(await request.json());
        return Response.json({ status: 'COUNTER_OFFER', version: 4 });
      }),
    );
    const dialog = await setup();
    expect(within(dialog).getByRole('button', { name: m.save })).toBeDisabled();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    expect(await within(dialog).findByTestId('bank-manual-result')).toHaveTextContent(
      /123\s456\s₽/,
    );
    expect(within(dialog).getByTestId('bank-manual-result')).toHaveTextContent('2,345');
    expect(saves).toHaveLength(0);
    await userEvent.dblClick(within(dialog).getByRole('button', { name: m.save }));
    expect(await screen.findByText(t.saved)).toBeInTheDocument();
    expect(previews).toHaveLength(1);
    expect(saves).toHaveLength(1);
    expect(previews[0]).toMatchObject({
      expectedVersion: 3,
      terms: { amountRub: 10000000, termMonths: 60, ratePercent: null },
    });
    expect(saves[0]).toMatchObject({
      outcome: 'COUNTER_OFFER',
      evaluationRef: 'checked-terms',
      expectedVersion: 3,
    });
    expect(saves[0]).not.toHaveProperty('terms');
  });

  it('правка поля отменяет предыдущий расчёт и требует повторной проверки', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        Response.json(evaluation()),
      ),
    );
    const dialog = await setup();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    await within(dialog).findByTestId('bank-manual-result');
    expect(within(dialog).getByRole('button', { name: m.save })).toBeEnabled();
    await userEvent.type(within(dialog).getByLabelText(t.comment), ' Дополнение');
    expect(within(dialog).queryByTestId('bank-manual-result')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: m.save })).toBeDisabled();
  });

  it('жёсткий запрет оставляет сохранение недоступным, даже если числа посчитаны', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        Response.json(
          evaluation({
            allowed: false,
            evaluationRef: null,
            violations: [{ code: 'RATE_OUT_OF_CORRIDOR', kind: 'HARD', params: {} }],
          }),
        ),
      ),
    );
    const dialog = await setup();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    expect(await within(dialog).findByText(m.denied)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: m.save })).toBeDisabled();
    expect(within(dialog).getByText(/Ставка вне допустимого коридора/)).toBeInTheDocument();
  });

  it('L1 может проверить меньшие условия даже когда первоначальный запрос требовал L2', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        Response.json(evaluation()),
      ),
    );
    const dialog = await setup('L1', 'L2');
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    expect(await within(dialog).findByText('Требуемый уровень решения: L1')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: m.save })).toBeEnabled();
  });

  it('старая версия расчёта блокирует повтор до обновления карточки', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        problemResponse({ status: 409, code: 'VERSION_CONFLICT' }),
      ),
    );
    const dialog = await setup();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    expect(await within(dialog).findByText(t.changed)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: m.calculate })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: m.save })).toBeDisabled();
  });

  it('повтор сохранения после сети сохраняет ключ/тело и запрещает менять неизвестный результат', async () => {
    const calls: { key: string | null; body: unknown }[] = [];
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        Response.json(evaluation()),
      ),
      http.post('*/api/backoffice/applications/:id/decision', async ({ request }) => {
        calls.push({ key: request.headers.get('Idempotency-Key'), body: await request.json() });
        return calls.length === 1
          ? HttpResponse.error()
          : Response.json({ status: 'COUNTER_OFFER', version: 4 });
      }),
    );
    const dialog = await setup();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    await within(dialog).findByTestId('bank-manual-result');
    await userEvent.click(within(dialog).getByRole('button', { name: m.save }));
    await waitFor(() => expect(within(dialog).getByLabelText(m.amount)).toBeDisabled());
    await userEvent.click(within(dialog).getByRole('button', { name: m.save }));
    expect(await screen.findByText(t.saved)).toBeInTheDocument();
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0]?.key).toBeTruthy();
  });

  it('форма и результат не содержат блокирующих нарушений доступности', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/evaluate-offer', () =>
        Response.json(evaluation()),
      ),
    );
    const dialog = await setup();
    await ready(dialog);
    await userEvent.click(within(dialog).getByRole('button', { name: m.calculate }));
    await within(dialog).findByTestId('bank-manual-result');
    expect(await blockingA11yViolations(document.body)).toEqual([]);
  });
});
