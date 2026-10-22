import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { VariantCard } from '@/components/VariantCard';
import { blockingA11yViolations } from '@/test/a11y';
import { renderWithProviders } from '@/test/render';
import { defaultOptions } from '@/test/wizardFactory';
import { termHints, variantCard } from '@/texts';

describe('карточка варианта', () => {
  it('показывает только то, что передали: числа не считаются и не выдумываются', () => {
    renderWithProviders(<VariantCard id="solo" title="Овердрафт" />);
    const card = screen.getByTestId('variant-card');
    expect(within(card).getByRole('heading', { level: 3, name: 'Овердрафт' })).toBeInTheDocument();
    expect(card).not.toHaveTextContent(variantCard.amount);
    expect(card).not.toHaveTextContent(variantCard.rate);
    expect(card).not.toHaveTextContent(variantCard.decision);
    expect(card).toHaveTextContent(variantCard.paymentLater);
    expect(screen.queryByText(variantCard.recommendedBadge)).not.toBeInTheDocument();
  });

  it('полная карточка: все строки, метка, действие и доступность', async () => {
    const { container } = renderWithProviders(
      <VariantCard
        id="full"
        title="Экспресс-кредит"
        headingLevel={2}
        recommended
        why="Быстро и без залога"
        amountRub={500_000}
        termMonths={12}
        paymentRub={46_677}
        paymentKind="ANNUITY"
        overpaymentRub={60_124}
        ratePercentFrom={21.5}
        approximate
        decisionTime="AUTO"
        documents={['Номер контракта']}
        comfortableOptions={defaultOptions}
        actions={<button type="button">Выбрать этот вариант</button>}
      />,
    );
    const card = screen.getByTestId('variant-card');
    expect(within(card).getByRole('heading', { level: 2 })).toHaveTextContent('Экспресс-кредит');
    expect(card).toHaveTextContent('Рекомендуем');
    expect(card).toHaveTextContent('от 21,5% в год');
    expect(card).toHaveTextContent('Номер контракта');
    expect(card).toHaveTextContent('Другие сроки');
    expect(within(card).getByRole('button', { name: 'Выбрать этот вариант' })).toBeInTheDocument();
    // название связано с карточкой для скринридера
    expect(screen.getByRole('article', { name: 'Экспресс-кредит' })).toBe(card);
    expect(await blockingA11yViolations(container)).toEqual([]);
  });

  it('ставка без пометки «ориентировочно», когда она итоговая', () => {
    renderWithProviders(
      <VariantCard id="final" title="Кредит" ratePercentFrom={21} approximate={false} />,
    );
    expect(screen.getByTestId('variant-card')).not.toHaveTextContent(variantCard.rateApproximate);
  });

  it('слово «Ставка» объясняется по клавише Tab', async () => {
    const user = userEvent.setup();
    renderWithProviders(<VariantCard id="hint" title="Кредит" ratePercentFrom={21} />);
    await user.tab();
    await user.tab();
    expect(screen.getByRole('button', { name: termHints.rate.term })).toHaveFocus();
    expect(await screen.findByText(termHints.rate.hint)).toBeInTheDocument();
  });
});
