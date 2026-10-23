import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { BankApplicationCard } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeBankCard, makeBankDecision } from '@/test/bankFactory';
import { makeBankMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { errorTexts } from '@/texts';
import { bankActions as t } from '@/texts/bankActions';

function setup(card: BankApplicationCard = makeBankCard(), level: 'L1' | 'L2' = 'L2') {
  mockSessions({ bank: makeBankMe('UNDERWRITER', { level }) });
  server.use(http.get('*/api/backoffice/applications/:id', () => Response.json(card)));
  return renderApp('/bank/applications/bank-app?expectedVersion=3');
}

async function open(label: string) {
  await userEvent.click(await screen.findByRole('button', { name: label }));
  return screen.findByRole('dialog');
}

describe('действия сотрудника банка (TS-032…TS-035)', () => {
  it('одобряет без причины при согласии с ядром, двойной клик даёт один запрос', async () => {
    const calls: { body: unknown; key: string | null }[] = [];
    server.use(
      http.post('*/api/backoffice/applications/:id/decision', async ({ request }) => {
        calls.push({ body: await request.json(), key: request.headers.get('Idempotency-Key') });
        return Response.json({
          applicationId: 'bank-app',
          decisionId: 'human',
          status: 'APPROVED',
          version: 4,
        });
      }),
    );
    setup();
    const dialog = await open(t.approve);
    expect(dialog).toHaveTextContent(t.agreement);
    expect(within(dialog).queryByLabelText(t.comment)).not.toBeInTheDocument();
    await userEvent.dblClick(within(dialog).getByRole('button', { name: t.confirm }));
    expect(await screen.findByText(t.saved)).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.key).toBeTruthy();
    expect(calls[0]?.body).toMatchObject({
      expectedVersion: 3,
      outcome: 'APPROVED',
      terms: { productCode: 'INVESTMENT', amountRub: 15_000_000, termMonths: 60 },
      reasonCode: null,
      comment: null,
    });
  });

  it('отказ вопреки ядру требует категории и 20 символов; для другого — 50', async () => {
    setup();
    const dialog = await open(t.reject);
    const submit = within(dialog).getByRole('button', { name: t.confirm });
    const comment = within(dialog).getByLabelText(t.comment, { exact: false });
    expect(submit).toBeDisabled();
    await userEvent.selectOptions(
      within(dialog).getByLabelText(t.reason, { exact: false }),
      'UW_RISK_HIGHER',
    );
    await userEvent.type(comment, 'x'.repeat(19));
    expect(submit).toBeDisabled();
    await userEvent.type(comment, 'x');
    expect(submit).toBeEnabled();
    await userEvent.selectOptions(
      within(dialog).getByLabelText(t.reason, { exact: false }),
      'UW_OTHER',
    );
    expect(submit).toBeDisabled();
    await userEvent.type(comment, 'x'.repeat(30));
    expect(submit).toBeEnabled();
  });

  it('L1 видит запрет решения уровня L2, но может запросить информацию', async () => {
    setup(makeBankCard({ decision: makeBankDecision({ requiredLevel: 'L2' }) }), 'L1');
    expect(await screen.findByText(t.lowerLevel)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t.approve })).toBeDisabled();
    expect(screen.getByRole('button', { name: t.info })).toBeEnabled();
    expect(screen.getByRole('button', { name: t.recheck })).toBeEnabled();
  });

  it('выбирает готовый вариант ядра и передаёт его ставку без собственного пересчёта', async () => {
    let body: unknown;
    server.use(
      http.post('*/api/backoffice/applications/:id/decision', async ({ request }) => {
        body = await request.json();
        return Response.json({ applicationId: 'bank-app', status: 'COUNTER_OFFER', version: 4 });
      }),
    );
    setup(
      makeBankCard({
        decision: makeBankDecision({
          variants: [
            {
              kind: 'SMALLER',
              productCode: 'INVESTMENT',
              amountRub: 10_000_000,
              termMonths: 60,
              ratePercent: 19.5,
              paymentRub: 262_164,
              dscr: 2,
              stressDscr: 1.5,
              securityRequired: false,
              recommended: true,
              note: '',
              requirements: [],
            },
          ],
        }),
      }),
    );
    const dialog = await open(t.counter);
    await userEvent.selectOptions(
      within(dialog).getByLabelText(t.reason, { exact: false }),
      'UW_RISK_HIGHER',
    );
    await userEvent.type(
      within(dialog).getByLabelText(t.comment, { exact: false }),
      'Риск по документам требует уменьшить сумму',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: t.confirm }));
    expect(await screen.findByText(t.saved)).toBeInTheDocument();
    expect(body).toMatchObject({
      outcome: 'COUNTER_OFFER',
      terms: {
        productCode: 'INVESTMENT',
        amountRub: 10_000_000,
        termMonths: 60,
        ratePercent: 19.5,
      },
    });
  });

  it('устаревшая карточка запрещает все действия', async () => {
    setup(makeBankCard({ stale: true }));
    const actions = await screen.findByTestId('bank-actions');
    for (const button of within(actions).getAllByRole('button')) expect(button).toBeDisabled();
  });

  it('409 версии блокирует повторное подтверждение и сохраняет введённое пояснение', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/decision', () =>
        problemResponse({ status: 409, code: 'VERSION_CONFLICT' }),
      ),
    );
    setup();
    const dialog = await open(t.reject);
    await userEvent.selectOptions(
      within(dialog).getByLabelText(t.reason, { exact: false }),
      'UW_RISK_HIGHER',
    );
    const comment = within(dialog).getByLabelText(t.comment, { exact: false });
    await userEvent.type(comment, 'Документы показывают существенный дополнительный риск');
    await userEvent.click(within(dialog).getByRole('button', { name: t.confirm }));
    expect(await within(dialog).findByText(t.changed)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: t.confirm })).toBeDisabled();
    expect(comment).toHaveValue('Документы показывают существенный дополнительный риск');
  });

  it('показывает понятный отказ в полномочиях от сервера', async () => {
    server.use(
      http.post('*/api/backoffice/applications/:id/decision', () =>
        problemResponse({ status: 403, code: 'AUTHORITY_LEVEL_TOO_LOW' }),
      ),
    );
    setup();
    const dialog = await open(t.approve);
    await userEvent.click(within(dialog).getByRole('button', { name: t.confirm }));
    expect(await screen.findByText(errorTexts.AUTHORITY_LEVEL_TOO_LOW.text)).toBeInTheDocument();
  });

  it('запрашивает пояснение с причиной и понятным описанием клиенту', async () => {
    let body: unknown;
    server.use(
      http.post('*/api/backoffice/applications/:id/request-info', async ({ request }) => {
        body = await request.json();
        return Response.json({
          applicationId: 'bank-app',
          status: 'NEEDS_INFO',
          version: 4,
          round: 1,
          taskIds: ['task'],
        });
      }),
    );
    setup();
    const dialog = await open(t.info);
    const submit = within(dialog).getByRole('button', { name: t.confirm });
    expect(submit).toBeDisabled();
    await userEvent.type(
      within(dialog).getByLabelText(t.taskTitle, { exact: false }),
      'Поясните закупку',
    );
    await userEvent.type(
      within(dialog).getByLabelText(t.why, { exact: false }),
      'Для проверки плана расходов',
    );
    await userEvent.click(submit);
    expect(await screen.findByText(t.requested)).toBeInTheDocument();
    expect(body).toMatchObject({
      expectedVersion: 3,
      reasonCode: 'UW_NEW_INFO',
      items: [
        { kind: 'EXPLANATION', title: 'Поясните закупку', whyText: 'Для проверки плана расходов' },
      ],
    });
  });

  it('повтор после обрыва сохраняет ключ и тело, пока результат неизвестен', async () => {
    const calls: { key: string | null; body: unknown }[] = [];
    server.use(
      http.post('*/api/backoffice/applications/:id/recheck', async ({ request }) => {
        calls.push({ key: request.headers.get('Idempotency-Key'), body: await request.json() });
        return calls.length === 1
          ? HttpResponse.error()
          : Response.json({
              applicationId: 'bank-app',
              status: 'CHECKING',
              version: 4,
              runId: 'run',
            });
      }),
    );
    setup();
    const dialog = await open(t.recheck);
    await userEvent.click(within(dialog).getByRole('button', { name: t.confirm }));
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: t.confirm })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole('button', { name: t.confirm }));
    expect(await screen.findByText(t.checking)).toBeInTheDocument();
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0]?.key).toBeTruthy();
  });

  it('показывает отправленный ответ, но не выводит черновик даже из ошибочного ответа API', async () => {
    setup(
      makeBankCard({
        latestAnsweredRound: 1,
        clientTasks: [
          {
            id: 'task',
            round: 1,
            kind: 'EXPLANATION',
            title: 'Поясните',
            whyText: 'Для проверки',
            what: '',
            where: '',
            status: 'OPEN',
            expiresAt: null,
            assigneeUserId: null,
            assigneePersonInn: null,
            answer: 'Черновик не для банка',
            answeredBy: null,
            answeredAt: null,
            createdAt: '2026-10-21T10:00:00Z',
          },
        ],
      }),
    );
    const requests = await screen.findByTestId('bank-client-requests');
    expect(requests).toHaveTextContent(t.waiting);
    expect(requests).not.toHaveTextContent('Черновик не для банка');
  });

  it('форма отказа доступна с клавиатуры и не содержит серьёзных нарушений axe', async () => {
    setup();
    await open(t.reject);
    expect(await blockingA11yViolations(document.body)).toEqual([]);
  });
});
