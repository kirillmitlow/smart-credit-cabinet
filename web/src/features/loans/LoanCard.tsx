import { Badge, Button, Card, Group, Stack, Text, VisuallyHidden } from '@mantine/core';
import { Link } from 'react-router';
import type { LoanOut } from '@/api/generated/model';
import { formatDate, formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { fill, loansTexts as t, productName } from '@/texts';
import { isLimitLoan, loanLimitOrAmount, loanStatusLabel } from './loanModel';

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={0}>
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fw={600}>{value}</Text>
    </Stack>
  );
}

/** Карточка кредита в списке и на главной: продукт, сумма или лимит, остаток, ближайший платёж */
export function LoanCard({ loan }: { loan: LoanOut }) {
  const limit = isLimitLoan(loan);
  const status = loanStatusLabel(loan.status);
  const heading = fill(t.card.number, { number: loan.contractNumber });
  const next = loan.nextPayment;
  return (
    <Card withBorder padding="md" data-testid="loan-card">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap="sm">
          <Stack gap={2}>
            <Text fw={600}>{productName(loan.productCode)}</Text>
            <Text size="sm" c="dimmed">
              {heading}. {fill(t.card.openedOn, { date: formatDate(loan.openedOn) })}
            </Text>
          </Stack>
          <Group gap="xl" align="flex-start">
            <Fact
              label={limit ? t.card.limit : t.card.amount}
              value={formatMoney(loanLimitOrAmount(loan))}
            />
            {limit ? null : (
              <Fact label={t.card.outstanding} value={formatMoney(loan.outstandingRub)} />
            )}
            <Fact label={t.card.rate} value={formatPercent(Number(loan.ratePercent))} />
            {limit ? null : (
              <Fact
                label={t.card.nextPayment}
                value={
                  next
                    ? fill(t.card.nextPaymentValue, {
                        amount: formatMoney(next.totalRub),
                        date: formatDate(next.dueDate),
                      })
                    : t.card.noNextPayment
                }
              />
            )}
            {limit ? <Fact label={t.card.term} value={formatTermMonths(loan.termMonths)} /> : null}
          </Group>
          {limit ? <Text size="sm">{t.card.limitNote}</Text> : null}
        </Stack>
        <Group gap="md" wrap="nowrap">
          {status ? (
            <Badge variant="light" size="lg" data-testid="loan-status">
              {status}
            </Badge>
          ) : null}
          <Button component={Link} to={`/loans/${loan.id}`} variant="light">
            {t.card.open}
            <VisuallyHidden>{` ${heading}`}</VisuallyHidden>
          </Button>
        </Group>
      </Group>
    </Card>
  );
}
