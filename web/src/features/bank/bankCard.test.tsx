import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { describe, expect, it } from 'vitest';
import type { BankApplicationCard } from '@/api/generated/model';
import { blockingA11yViolations } from '@/test/a11y';
import { makeBankCard, makeBankDecision } from '@/test/bankFactory';
import { MockEventSource } from '@/test/eventSource';
import { makeBankMe, problemResponse } from '@/test/factories';
import { renderApp } from '@/test/render';
import { server } from '@/test/server';
import { mockSessions } from '@/test/sessions';
import { errorTexts } from '@/texts';
import { bankCard as t } from '@/texts/bank';

function card(value: BankApplicationCard) {
  server.use(http.get('*/api/backoffice/applications/:id', () => Response.json(value)));
}

describe('банковская карточка (TS-031)', () => {
  it('показывает все блоки оценки и не выдаёт недоступные документы за пустой список', async () => {
    mockSessions({ bank: makeBankMe() });
    card(makeBankCard());
    const { container } = renderApp('/bank/applications/bank-app?expectedVersion=3');
    await screen.findByRole('heading', { name: 'Заявка АЗ-2026-000001' });
    expect(screen.getByText('ООО «СтанкоПром»')).toBeInTheDocument();
    expect(screen.getByText(/Белова Мария/)).toHaveTextContent('Бухгалтер');
    for (const block of [
      'bank-factors',
      'bank-money',
      'bank-rate',
      'bank-flags',
      'bank-variants',
      'bank-sources',
      'bank-history',
      'bank-documents',
    ]) {
      expect(screen.getByTestId(block)).toBeInTheDocument();
    }
    expect(screen.getByText(/Баллы: 90 из 100. Грейд: A/)).toBeInTheDocument();
    expect(screen.getAllByRole('meter')).toHaveLength(9);
    expect(screen.getByTestId('bank-money')).toHaveTextContent(/393\s247\s₽/);
    expect(screen.getByTestId('bank-rate')).toHaveTextContent('19,5%');
    expect(screen.getByTestId('bank-documents')).toHaveTextContent(t.documentsUnavailable);
    expect(screen.queryByText(t.noDocuments)).not.toBeInTheDocument();
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('показывает решение проверки с сервера без собственного пересчёта порога', async () => {
    mockSessions({ bank: makeBankMe() });
    card(
      makeBankCard({
        decision: makeBankDecision({
          checks: [
            {
              code: 'DSCR',
              title: 'Покрытие платежей',
              value: 2,
              threshold: 1.25,
              comparison: 'MIN',
              passed: false,
            },
          ],
        }),
      }),
    );
    renderApp('/bank/applications/bank-app?expectedVersion=3');
    const money = await screen.findByTestId('bank-money');
    expect(within(money).getByText(t.failed)).toBeInTheDocument();
    expect(within(money).queryByText(t.passed)).not.toBeInTheDocument();
  });

  it('прямой вход запоминает первую версию, событие показывает смену статуса, обновление подтверждает новую', async () => {
    mockSessions({ bank: makeBankMe() });
    let version = 3;
    const requested: (string | null)[] = [];
    server.use(
      http.get('*/api/backoffice/applications/:id', ({ request }) => {
        const expected = new URL(request.url).searchParams.get('expectedVersion');
        requested.push(expected);
        return Response.json(
          makeBankCard({
            version,
            stale: expected !== null && Number(expected) !== version,
            status: version === 3 ? 'MANUAL_REVIEW' : 'WITHDRAWN',
          }),
        );
      }),
    );
    renderApp('/bank/applications/bank-app');
    await screen.findByTestId('bank-factors');
    await waitFor(() => expect(requested).toContain('3'));
    version = 4;
    act(() => {
      MockEventSource.latest().open();
      MockEventSource.latest().emit('status_changed', {}, 2);
    });
    expect(await screen.findByTestId('bank-card-stale')).toHaveTextContent(t.changed);
    await userEvent.click(screen.getByRole('button', { name: t.refresh }));
    await waitFor(() => expect(screen.queryByTestId('bank-card-stale')).not.toBeInTheDocument());
    expect(window.location.search).toContain('expectedVersion=4');
    expect(requested).toContain('4');
  });

  it('неполнота относится к текущему источнику; ссылка ведёт к действию перепроверки', async () => {
    mockSessions({ bank: makeBankMe() });
    const data = makeBankCard();
    card({
      ...data,
      sourceSnapshots: data.sourceSnapshots.map((s) => ({ ...s, status: 'UNAVAILABLE' })),
    });
    renderApp('/bank/applications/bank-app?expectedVersion=3');
    expect(await screen.findByText(t.incomplete)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t.recheck })).toBeEnabled();
    expect(screen.getByRole('link', { name: t.recheck })).toHaveAttribute('href', '#bank-actions');
  });

  it('снимки показывают обе даты и номер запроса; исходные значения выводятся текстом', async () => {
    mockSessions({ bank: makeBankMe() });
    const data = makeBankCard();
    card({
      ...data,
      sourceSnapshots: data.sourceSnapshots.map((s) => ({
        ...s,
        payload: { name: '<img src=x onerror=alert(1)>', status: 'ACTIVE' },
      })),
    });
    const { container } = renderApp('/bank/applications/bank-app?expectedVersion=3');
    const sources = await screen.findByTestId('bank-sources');
    expect(sources).toHaveTextContent('req-registry');
    expect(sources).toHaveTextContent(/18\sокт\s2026/);
    expect(sources).toHaveTextContent(/21 октября/);
    await userEvent.click(within(sources).getByText(t.original));
    expect(within(sources).getByText('<img src=x onerror=alert(1)>')).toBeVisible();
    expect(container.querySelector('img[src="x"]')).toBeNull();
  });

  it('сверка и варианты отображают готовые числа и требования ядра', async () => {
    mockSessions({ bank: makeBankMe() });
    card(
      makeBankCard({
        decision: makeBankDecision({
          comparisons: [
            {
              code: 'mismatch_turnover_fin',
              aRub: 60_000_000,
              bRub: 36_000_000,
              deviationPercent: 66.6667,
              year: 2025,
            },
          ],
          variants: [
            {
              kind: 'KEEP_TERM',
              productCode: 'WORKING_CAPITAL',
              amountRub: 3_850_000,
              termMonths: 12,
              ratePercent: 19.5,
              paymentRub: 355_000,
              dscr: 1.3,
              stressDscr: 1.05,
              securityRequired: true,
              recommended: true,
              note: 'Запас по платежу',
              requirements: ['Подтвердить залог'],
            },
          ],
        }),
      }),
    );
    renderApp('/bank/applications/bank-app?expectedVersion=3');
    const flags = await screen.findByTestId('bank-flags');
    expect(flags).toHaveTextContent('66,67%');
    const variants = screen.getByTestId('bank-variants');
    expect(variants).toHaveTextContent(/3\s850\s000\s₽/);
    expect(variants).toHaveTextContent('Подтвердить залог');
    expect(variants).toHaveTextContent(t.recommended);
  });

  it('ошибка с повтором затем загружает карточку; 404 явно показывает отсутствие заявки', async () => {
    mockSessions({ bank: makeBankMe() });
    server.use(
      http.get('*/api/backoffice/applications/:id', () =>
        problemResponse({ status: 503, code: 'UNKNOWN_ERROR' }),
      ),
    );
    renderApp('/bank/applications/bank-app?expectedVersion=3');
    await screen.findByText(errorTexts.UNKNOWN_ERROR.text);
    card(makeBankCard());
    await userEvent.click(
      screen.getByRole('button', { name: errorTexts.UNKNOWN_ERROR.action ?? '' }),
    );
    expect(await screen.findByTestId('bank-factors')).toBeInTheDocument();
  });

  it('404 не ведёт сотрудника в клиентскую зону', async () => {
    mockSessions({ bank: makeBankMe() });
    renderApp('/bank/applications/missing?expectedVersion=3');
    expect(await screen.findByText(t.notFound)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t.back })).toHaveAttribute('href', '/bank');
  });
});
