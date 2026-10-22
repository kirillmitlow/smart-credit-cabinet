import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { LoanDetail } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { testOffer } from '@/test/contractFactory';
import { makeMe, problemResponse } from '@/test/factories';
import { makeAnnuityLoan, makeBulletLoan, makeCreditLine, toListItem } from '@/test/loanFactory';
import { renderApp } from '@/test/render';
import { mockSessions } from '@/test/sessions';
import { server } from '@/test/server';
import { emptyStates, errorTexts, loansTexts as t, home } from '@/texts';
import { NBSP, formatDate as fmtDate, formatMoney } from '@/lib/format';
import { isLimitLoan, scheduleTotals, withBalances } from './loanModel';

/** `toHaveTextContent` сворачивает неразрывные пробелы, поэтому ждём текст в том же виде */
const plain = (text: string) => text.replaceAll(NBSP, ' ');
const money = (rub: number) => plain(formatMoney(rub));
const formatDate = (iso: string) => plain(fmtDate(iso));

function mockList(loans: LoanDetail[]) {
  server.use(
    http.get('*/api/loans', () =>
      Response.json({ items: loans.map(toListItem), nextCursor: null }),
    ),
  );
}

function mockLoan(loan: LoanDetail, contractId: string | null = 'contract-1') {
  server.use(
    http.get(`*/api/loans/${loan.id}`, () => Response.json(loan)),
    http.get(`*/api/applications/${loan.applicationId}/offer`, () =>
      contractId === null
        ? problemResponse({ status: 404, code: 'NOT_FOUND' })
        : Response.json(testOffer({ applicationId: loan.applicationId, contractId })),
    ),
  );
}

describe('мои кредиты: список', () => {
  it('пусто: честная подпись и путь к подбору', async () => {
    mockSessions({ client: makeMe() });
    const { container } = renderApp('/loans');
    expect(await screen.findByRole('heading', { level: 1, name: t.title })).toBeInTheDocument();
    const empty = await screen.findByTestId('loans-empty');
    expect(within(empty).getByText(emptyStates.loans)).toBeInTheDocument();
    expect(within(empty).getByRole('link', { name: t.emptyAction })).toHaveAttribute(
      'href',
      '/wizard',
    );
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('кредит с графиком: продукт, сумма, остаток, ставка и ближайший платёж', async () => {
    mockSessions({ client: makeMe() });
    const loan = makeAnnuityLoan();
    mockList([loan]);
    const { container } = renderApp('/loans');
    const card = await screen.findByTestId('loan-card');
    expect(card).toHaveTextContent('Экспресс-кредит');
    expect(card).toHaveTextContent('КД-2026-000001');
    expect(card).toHaveTextContent(`${t.card.amount}${money(300_000)}`);
    expect(card).toHaveTextContent(`${t.card.outstanding}${money(300_000)}`);
    expect(card).toHaveTextContent('21,5%');
    expect(card).toHaveTextContent(
      `${t.card.nextPayment}${money(103_000)}, ${formatDate('2026-11-21')}`,
    );
    expect(within(card).getByTestId('loan-status')).toHaveTextContent(t.status.ACTIVE);
    expect(within(card).getByRole('link', { name: /Открыть/ })).toHaveAttribute(
      'href',
      '/loans/loan-1',
    );
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('кредитная линия: только лимит и ставка, без остатка и ближайшего платежа', async () => {
    mockSessions({ client: makeMe() });
    mockList([makeCreditLine()]);
    renderApp('/loans');
    const card = await screen.findByTestId('loan-card');
    expect(card).toHaveTextContent('Кредитная линия');
    expect(card).toHaveTextContent(`${t.card.limit}${money(1_000_000)}`);
    expect(card).toHaveTextContent(t.card.limitNote);
    expect(card).not.toHaveTextContent(t.card.nextPayment);
    expect(card).not.toHaveTextContent(t.card.outstanding);
  });

  it('все платежи по графику прошли: так и пишем', async () => {
    mockSessions({ client: makeMe() });
    mockList([makeAnnuityLoan({ nextPayment: null })]);
    renderApp('/loans');
    expect(await screen.findByText(t.card.noNextPayment)).toBeInTheDocument();
  });

  it('ошибка загрузки: текст по коду и «Повторить», потом список', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/loans', () =>
        problemResponse({ status: 500, code: 'UNKNOWN_ERROR', requestId: 'req-loans' }),
      ),
    );
    renderApp('/loans');
    expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.getByText(/req-loans/)).toBeInTheDocument();
    mockList([makeAnnuityLoan()]);
    await user.click(screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action ?? '' }));
    expect(await screen.findByTestId('loan-card')).toBeInTheDocument();
  });

  it('клик по «Открыть» ведёт на страницу кредита', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    const loan = makeAnnuityLoan();
    mockList([loan]);
    mockLoan(loan);
    renderApp('/loans');
    await user.click(await screen.findByRole('link', { name: /Открыть/ }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Экспресс-кредит' })).toBeVisible();
    expect(window.location.pathname).toBe('/loans/loan-1');
  });
});

describe('мои кредиты: страница кредита', () => {
  it('равные платежи: условия, график, итог = долг + проценты, платёж как в графике', async () => {
    mockSessions({ client: makeMe() });
    const loan = makeAnnuityLoan();
    mockLoan(loan);
    const { container } = renderApp('/loans/loan-1');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Экспресс-кредит' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Договор № КД-2026-000001')).toBeInTheDocument();

    const rows = await screen.findAllByTestId('schedule-row');
    expect(rows).toHaveLength(3);
    // платёж в условиях совпадает с первой строкой графика
    const first = rows[0] as HTMLElement;
    expect(first).toHaveTextContent(money(103_000));
    expect(screen.getByText(t.detail.payment).nextElementSibling).toHaveTextContent(money(103_000));
    // остаток долга после платежей: 200 000, 100 000, 0
    expect(rows.map((row) => within(row).getAllByRole('cell').at(-1)?.textContent)).toEqual([
      formatMoney(200_000),
      formatMoney(100_000),
      formatMoney(0),
    ]);
    // ближайший платёж помечен
    expect(first).toHaveAttribute('data-next', 'true');
    expect(within(first).getByText(t.detail.nextBadge)).toBeInTheDocument();
    expect(rows[1]).toHaveAttribute('data-next', 'false');
    // итог: платежи = долг + проценты
    const total = within(screen.getByTestId('schedule-total'));
    expect(total.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      formatMoney(306_000),
      formatMoney(300_000),
      formatMoney(6_000),
    ]);
    // реквизиты и оговорка
    expect(screen.getByText(loan.settlementAccount)).toBeInTheDocument();
    expect(screen.getByText(loan.loanAccount)).toBeInTheDocument();
    expect(screen.getByText(t.detail.notModelled)).toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('«Скачать договор» ведёт на документ договора заявки', async () => {
    mockSessions({ client: makeMe() });
    mockLoan(makeAnnuityLoan());
    renderApp('/loans/loan-1');
    expect(await screen.findByRole('link', { name: t.detail.document })).toHaveAttribute(
      'href',
      '/api/contracts/contract-1/document',
    );
  });

  it('договор не нашёлся: страница работает, ссылки нет', async () => {
    mockSessions({ client: makeMe() });
    mockLoan(makeAnnuityLoan(), null);
    renderApp('/loans/loan-1');
    await screen.findAllByTestId('schedule-row');
    expect(screen.queryByRole('link', { name: t.detail.document })).not.toBeInTheDocument();
  });

  it('под контракт: проценты каждый месяц, долг одной суммой в конце', async () => {
    mockSessions({ client: makeMe() });
    mockLoan(makeBulletLoan());
    renderApp('/loans/loan-2');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Кредит под контракт' }),
    ).toBeInTheDocument();
    expect(screen.getByText(t.repayment.BULLET)).toBeInTheDocument();
    expect(screen.getByText(t.detail.interestPayment).nextElementSibling).toHaveTextContent(
      money(5_000),
    );
    expect(screen.getByText(t.detail.principalAtEnd).nextElementSibling).toHaveTextContent(
      money(300_000),
    );
    const rows = await screen.findAllByTestId('schedule-row');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent(money(305_000));
    const total = within(screen.getByTestId('schedule-total'));
    expect(total.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      formatMoney(315_000),
      formatMoney(300_000),
      formatMoney(15_000),
    ]);
  });

  it('кредитная линия: лимит и ставка, графика и «ближайшего платежа» нет', async () => {
    mockSessions({ client: makeMe() });
    mockLoan(makeCreditLine());
    const { container } = renderApp('/loans/loan-3');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Кредитная линия' }),
    ).toBeInTheDocument();
    expect(screen.getByText(t.card.limit).nextElementSibling).toHaveTextContent(money(1_000_000));
    expect(screen.getByTestId('loan-limit-note')).toHaveTextContent(t.detail.limitNote);
    expect(screen.queryByTestId('schedule-table')).not.toBeInTheDocument();
    expect(screen.queryByText(t.card.nextPayment)).not.toBeInTheDocument();
    expect(screen.queryByText(t.card.outstanding)).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('чужой или несуществующий кредит: «Не нашли такой кредит» и путь к списку', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/loans/other', () => problemResponse({ status: 404, code: 'NOT_FOUND' })),
    );
    renderApp('/loans/other');
    expect(
      await screen.findByRole('heading', { level: 1, name: t.notFound.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(t.notFound.body)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t.notFound.toList })).toHaveAttribute('href', '/loans');
  });

  it('ошибка сервера: экран ошибки с «Повторить» и номером запроса', async () => {
    const user = userEvent.setup();
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/loans/loan-1', () =>
        problemResponse({ status: 500, code: 'UNKNOWN_ERROR', requestId: 'req-loan' }),
      ),
    );
    renderApp('/loans/loan-1');
    expect(await screen.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.getByText(/req-loan/)).toBeInTheDocument();
    mockLoan(makeAnnuityLoan());
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findAllByTestId('schedule-row')).toHaveLength(3);
  });
});

describe('мои кредиты: главная', () => {
  it('нет кредитов: подпись из словаря, ссылки «Все кредиты» нет', async () => {
    mockSessions({ client: makeMe() });
    renderApp('/');
    await screen.findByRole('heading', { level: 1, name: home.title });
    expect(await screen.findByTestId('loans-empty')).toHaveTextContent(emptyStates.loans);
    expect(screen.queryByRole('link', { name: t.home.all })).not.toBeInTheDocument();
  });

  it('есть кредиты: карточки в блоке и ссылка на полный список', async () => {
    mockSessions({ client: makeMe() });
    mockList([makeAnnuityLoan(), makeCreditLine()]);
    const { container } = renderApp('/');
    const section = within(await screen.findByRole('region', { name: home.loans.heading }));
    expect(await section.findAllByTestId('loan-card')).toHaveLength(2);
    expect(section.getByRole('link', { name: t.home.all })).toHaveAttribute('href', '/loans');
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('кредиты не загрузились: ошибка только в своём блоке', async () => {
    mockSessions({ client: makeMe() });
    server.use(
      http.get('*/api/loans', () => problemResponse({ status: 500, code: 'UNKNOWN_ERROR' })),
    );
    renderApp('/');
    const section = within(await screen.findByRole('region', { name: home.loans.heading }));
    expect(await section.findByText(errorTexts.UNKNOWN_ERROR.text)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: home.needMoney })).toBeInTheDocument();
  });
});

describe('модель кредита', () => {
  it('остаток после каждого платежа и итоги графика', () => {
    const loan = makeAnnuityLoan();
    const lines = withBalances(loan.schedule, loan.amountRub);
    expect(lines.map((line) => line.balanceRub)).toEqual([200_000, 100_000, 0]);
    const totals = scheduleTotals(loan.schedule);
    expect(totals.totalRub).toBe(totals.principalRub + totals.interestRub);
  });

  it('линия и овердрафт определяются по виду и по способу погашения', () => {
    expect(isLimitLoan(makeCreditLine())).toBe(true);
    expect(isLimitLoan(makeCreditLine({ kind: 'OVERDRAFT', repaymentType: 'REVOLVING' }))).toBe(
      true,
    );
    expect(isLimitLoan(makeAnnuityLoan())).toBe(false);
    expect(isLimitLoan(makeBulletLoan())).toBe(false);
  });
});
