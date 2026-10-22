import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { ClientDecisionOut } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeApplication, makeMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { decision as t, outcomes } from '@/texts';
import { makeDecision } from '@/test/decisionFactory';

function show(data: ClientDecisionOut, status = data.outcome, response?: () => Response) {
  mockSessions({ client: makeMe() });
  server.use(
    http.get('*/api/applications/app-1', () =>
      Response.json(
        makeApplication({
          status,
          amountRub: 900_000,
          termMonths: 36,
          allowedActions: [],
        }),
      ),
    ),
    http.get('*/api/applications/app-1/decision', () => response?.() ?? Response.json(data)),
  );
  return renderApp('/applications/app-1');
}

describe('T-422: объяснение решения клиенту', () => {
  it('TS-001: Соколова — условия снимка, разбивка ставки, факторы и график', async () => {
    const user = userEvent.setup();
    const { container } = show(makeDecision());
    await screen.findByText('чистая кредитная история');
    const panel = screen.getByRole('region', { name: outcomes.approved.title });
    expect(panel).toHaveTextContent(/500.000.₽/);
    expect(panel).toHaveTextContent(/12.месяцев/);
    expect(panel).toHaveTextContent('21,5%');
    expect(panel).toHaveTextContent(/46.677.₽/);
    expect(panel).toHaveTextContent(/60.126.₽/);
    expect(panel).not.toHaveTextContent(/900.000.₽/);
    expect(panel).toHaveTextContent('20 ноября');
    await user.click(within(panel).getByText(t.rateBreakdown));
    expect(within(panel).getByText('Базовая ставка')).toBeVisible();
    expect(within(panel).getByText('19,5%')).toBeVisible();
    await user.click(within(panel).getByText(t.schedule, { selector: 'summary' }));
    const schedule = within(panel).getByRole('table', { name: t.schedule });
    expect(within(schedule).getAllByRole('row')).toHaveLength(3);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('TS-009: Ромашка — причины и конкретные шаги берутся с сервера', async () => {
    const { container } = show(
      makeDecision({
        outcome: 'REJECTED',
        terms: null,
        offer: null,
        whatHelped: [],
        reasons: [
          {
            code: 'TAX_DEBT_HIGH',
            text: 'Долг по налогам 1 150 000 ₽',
            action: 'Погасите не менее 358 334 ₽',
          },
          {
            code: 'OVERDUE',
            text: 'Есть текущая просрочка',
            action: 'Погасите просроченную задолженность',
          },
        ],
        nextSteps: ['Погасите не менее 358 334 ₽', 'Погасите просроченную задолженность'],
      }),
    );
    expect(await screen.findByText('Долг по налогам 1 150 000 ₽')).toBeVisible();
    expect(screen.getByText('Погасите не менее 358 334 ₽')).toBeVisible();
    expect(screen.getByText('Есть текущая просрочка')).toBeVisible();
    expect(document.body.textContent).not.toMatch(
      /TAX_DEBT_HIGH|OVERDUE|DSCR|грейд|скоринг|стоп-фактор/i,
    );
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('TS-010: Вектор — причина ликвидации из снимка', async () => {
    show(
      makeDecision({
        outcome: 'REJECTED',
        terms: null,
        offer: null,
        whatHelped: [],
        reasons: [
          {
            code: 'COMPANY_NOT_ACTIVE',
            text: 'Компания не действует: идёт ликвидация',
            action: '',
          },
        ],
      }),
    );
    expect(await screen.findByText('Компания не действует: идёт ликвидация')).toBeVisible();
  });

  it('нейтральный отказ не раскрывает код и не придумывает рекомендации', async () => {
    show(
      makeDecision({
        outcome: 'REJECTED',
        terms: null,
        offer: null,
        whatHelped: [],
        reasons: [{ code: 'BANK_POLICY', text: 'Решение принято по правилам банка', action: '' }],
        nextSteps: [],
      }),
    );
    await screen.findByText('Решение принято по правилам банка');
    expect(screen.queryByText(outcomes.rejected.whatToDo)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/BANK_POLICY|AML|115-ФЗ/);
  });

  it('ошибка решения: видна ошибка, повтор загружает данные', async () => {
    const user = userEvent.setup();
    let broken = true;
    show(makeDecision(), 'APPROVED', () =>
      broken
        ? problemResponse({ status: 503, code: 'DIRECTORY_UNAVAILABLE' })
        : Response.json(makeDecision()),
    );
    const retry = await screen.findByRole('button', { name: 'Повторить' });
    broken = false;
    await user.click(retry);
    expect(await screen.findByText('стабильная выручка')).toBeVisible();
  });

  it('нет условий — не подставляет параметры заявки и не даёт принять', async () => {
    show(makeDecision({ terms: null }));
    expect(await screen.findByText(t.noTerms)).toBeVisible();
    expect(
      screen.queryByRole('button', { name: outcomes.approved.accept }),
    ).not.toBeInTheDocument();
  });

  it('разошедшийся исход предлагает обновление вместо неверных условий', async () => {
    show(makeDecision({ outcome: 'REJECTED', terms: null, offer: null }), 'APPROVED');
    expect(await screen.findByText(t.unavailable)).toBeVisible();
    expect(screen.getByRole('button', { name: t.refresh })).toBeEnabled();
  });
});
