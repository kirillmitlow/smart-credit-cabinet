import { Alert, Badge, Card, Grid, Group, Paper, Stack, Table, Text, Title } from '@mantine/core';
import type { BankDecision } from '@/api/generated/model';
import { formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { fill, productName } from '@/texts';
import { bankCard as t } from '@/texts/bank';
import { bankNumber } from './bankFormatting';

export function BankAssessmentPanels({
  decision: d,
  incomplete,
}: {
  decision: BankDecision | null;
  incomplete: boolean;
}) {
  if (!d) return <Alert color="gray">{t.noDecision}</Alert>;
  const facts = [
    [t.revenue, d.revenueMonthlyRub],
    [t.flow, d.freeCashFlowRub],
    [t.existingPayments, d.existingPaymentsRub],
    [t.payment, d.paymentRub],
    [t.lastPayment, d.lastPaymentRub],
    [t.overpayment, d.overpaymentRub],
    [t.maxAmount, d.maxAmountRub],
  ] as const;
  return (
    <>
      <Paper withBorder p="md" data-testid="bank-factors">
        <Title order={2} size="h3">
          {t.factors}
        </Title>
        <Text fw={600}>
          {fill(t.score, { score: d.score ?? t.noData, grade: d.grade ?? t.noData })}
        </Text>
        <Text size="sm">
          {t.pd}: {formatPercent(d.pdPercent)}
        </Text>
        {incomplete ? (
          <Alert color="yellow" mt="sm">
            {t.incomplete}
          </Alert>
        ) : null}
        <Table mt="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th scope="col">{t.factor}</Table.Th>
              <Table.Th scope="col">{t.points}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {d.factors.map((factor) => (
              <Table.Tr key={factor.code}>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {factor.title}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {factor.code} · {factor.value}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group>
                    <meter
                      min={0}
                      max={factor.maxPoints}
                      value={factor.points}
                      aria-label={factor.title}
                    />
                    <Text size="sm">
                      {fill(t.pointsValue, { points: factor.points, max: factor.maxPoints })}
                    </Text>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      <Paper withBorder p="md" data-testid="bank-money">
        <Title order={2} size="h3">
          {t.money}
        </Title>
        <Grid mt="xs">
          {facts.map(([label, value]) => (
            <Grid.Col key={label} span={{ base: 12, sm: 6, md: 4 }}>
              <Text size="xs" c="dimmed">
                {label}
              </Text>
              <Text fw={500}>{formatMoney(value)}</Text>
            </Grid.Col>
          ))}
        </Grid>
        <Text size="sm" mt="sm">
          {t.shock}: {formatPercent(d.stressShockPercent)}
        </Text>
        <Table mt="sm">
          <Table.Thead>
            <Table.Tr>
              {[t.check, t.value, t.threshold, t.result].map((label) => (
                <Table.Th scope="col" key={label}>
                  {label}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {d.checks.map((metric) => (
              <Table.Tr key={metric.code}>
                <Table.Td>{metric.title}</Table.Td>
                <Table.Td>{bankNumber(metric.value)}</Table.Td>
                <Table.Td>
                  {metric.threshold === null
                    ? t.noData
                    : fill(metric.comparison === 'MIN' ? t.minimum : t.maximum, {
                        value: bankNumber(metric.threshold),
                      })}
                </Table.Td>
                <Table.Td>
                  <Badge
                    variant="light"
                    c="dark.9"
                    color={metric.passed === null ? 'gray' : metric.passed ? 'green' : 'red'}
                  >
                    {metric.passed === null ? t.noData : metric.passed ? t.passed : t.failed}
                  </Badge>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
      <Paper withBorder p="md" data-testid="bank-rate">
        <Title order={2} size="h3">
          {t.rate}
        </Title>
        <Group gap="xl" mt="sm">
          <Text fw={600}>
            {t.finalRate}: {formatPercent(d.rate.ratePercent)}
          </Text>
          <Text size="sm">
            {t.corridor}: {formatPercent(d.rate.corridorMinPercent)} —{' '}
            {formatPercent(d.rate.corridorMaxPercent)}
          </Text>
        </Group>
        <Table mt="sm">
          <Table.Tbody>
            {d.rate.parts.map((part) => (
              <Table.Tr key={part.code}>
                <Table.Th scope="row" fw={500}>
                  {part.title}
                </Table.Th>
                <Table.Td>{formatPercent(part.percent, 4)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="sm" mt="xs">
          {t.rawRate}: {formatPercent(d.rate.rawRatePercent, 4)}
        </Text>
        {d.rate.rateWithCollateralPercent !== null ? (
          <Text size="sm">
            {t.collateralRate}: {formatPercent(d.rate.rateWithCollateralPercent)}
          </Text>
        ) : null}
      </Paper>
      <Paper withBorder p="md" data-testid="bank-flags">
        <Title order={2} size="h3">
          {t.flags}
        </Title>
        <Stack mt="sm" gap="sm">
          {d.reasons.length ? (
            d.reasons.map((reason, index) => (
              <div key={`${reason.code}-${index}`}>
                <Text fw={500} size="sm">
                  {reason.title}
                </Text>
                <Text size="sm">{reason.detail}</Text>
                <Text size="xs" c="dimmed">
                  {reason.code}
                </Text>
              </div>
            ))
          ) : (
            <Text>{t.noFlags}</Text>
          )}
        </Stack>
        {d.comparisons.length ? (
          <>
            <Title order={3} size="h4" mt="md">
              {t.comparisons}
            </Title>
            <Table.ScrollContainer minWidth={620}>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    {[t.check, t.comparisonA, t.comparisonB, t.deviation, t.year].map((label) => (
                      <Table.Th scope="col" key={label}>
                        {label}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {d.comparisons.map((comparison) => (
                    <Table.Tr key={comparison.code}>
                      <Table.Td>
                        {Object.prototype.hasOwnProperty.call(t.comparison, comparison.code)
                          ? t.comparison[comparison.code as keyof typeof t.comparison]
                          : comparison.code}
                      </Table.Td>
                      <Table.Td>{formatMoney(comparison.aRub)}</Table.Td>
                      <Table.Td>{formatMoney(comparison.bRub)}</Table.Td>
                      <Table.Td>{formatPercent(comparison.deviationPercent)}</Table.Td>
                      <Table.Td>{comparison.year ?? t.noData}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </>
        ) : null}
      </Paper>
      <Paper withBorder p="md" data-testid="bank-variants">
        <Title order={2} size="h3">
          {t.variants}
        </Title>
        {d.variants.length ? (
          <Grid mt="sm">
            {d.variants.map((variant, index) => (
              <Grid.Col key={`${variant.kind}-${index}`} span={{ base: 12, md: 4 }}>
                <Card withBorder>
                  <Title order={3} size="h4">
                    {fill(t.variant, { number: index + 1 })}
                  </Title>
                  {variant.recommended ? (
                    <Badge mt="xs" color="green" c="dark.9" variant="light">
                      {t.recommended}
                    </Badge>
                  ) : null}
                  <Text mt="sm" fw={600}>
                    {productName(variant.productCode)}
                  </Text>
                  <Text>
                    {formatMoney(variant.amountRub)} · {formatTermMonths(variant.termMonths)}
                  </Text>
                  <Text>
                    {formatPercent(variant.ratePercent)} · {formatMoney(variant.paymentRub)}
                  </Text>
                  <Text size="sm">
                    {t.dscr}: {bankNumber(variant.dscr)} · {t.stressDscr}:{' '}
                    {bankNumber(variant.stressDscr)}
                  </Text>
                  <Text size="sm" mt="xs">
                    {variant.note}
                  </Text>
                  {variant.securityRequired ? (
                    <Text size="sm" fw={500}>
                      {t.security}
                    </Text>
                  ) : null}
                  <Stack component="ul" gap={4} mt="xs">
                    {variant.requirements.map((requirement) => (
                      <Text component="li" size="sm" key={requirement}>
                        {requirement}
                      </Text>
                    ))}
                  </Stack>
                </Card>
              </Grid.Col>
            ))}
          </Grid>
        ) : (
          <Text mt="sm">{t.noVariants}</Text>
        )}
      </Paper>
    </>
  );
}
