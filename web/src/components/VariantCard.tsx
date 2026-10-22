import type { ReactNode } from 'react';
import { Badge, Card, Group, List, Stack, Text, Title } from '@mantine/core';
import type { ComfortableOption } from '@/api/generated/model';
import { DecisionTime, PaymentKind } from '@/api/generated/model';
import { TermHint } from '@/components/TermHint';
import { formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { fill, termHints } from '@/texts';
import { variantCard as t } from '@/texts/wizard';

export interface VariantCardProps {
  /** Уникальная основа для id заголовка (связывает карточку и её название для скринридера) */
  id: string;
  title: string;
  /** Уровень заголовка названия; по умолчанию 3 (карточки лежат под заголовком раздела) */
  headingLevel?: 2 | 3 | 4;
  /** Метка «Рекомендуем» */
  recommended?: boolean;
  /** «Почему подходит вам» одной фразой */
  why?: string | null;
  amountRub?: number | null;
  termMonths?: number | null;
  /** Платёж, как его посчитал бэкенд (на фронте ничего не считаем) */
  paymentRub?: number | null;
  paymentKind?: PaymentKind | null;
  overpaymentRub?: number | null;
  /** Ставка «от», % годовых */
  ratePercentFrom?: number | null;
  /** Ставка ориентировочная (до проверки) */
  approximate?: boolean;
  decisionTime?: DecisionTime | null;
  /** Документы: строки готовит бэкенд */
  documents?: readonly string[];
  needsCollateral?: boolean;
  needsContract?: boolean;
  needsSecurity?: boolean;
  /** Другие сроки с платежом и переплатой; выбранный срок выделяется */
  comfortableOptions?: readonly ComfortableOption[];
  /** Пометка или пояснение под карточкой (например, про путь «На запуск») */
  note?: ReactNode;
  /** Кнопки действий карточки */
  actions?: ReactNode;
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <Group justify="space-between" wrap="nowrap" align="baseline" gap="md">
      <Text component="dt" c="dimmed">
        {label}
      </Text>
      <Text component="dd" m={0} fw={600} ta="right">
        {children}
      </Text>
    </Group>
  );
}

/**
 * Карточка варианта (60-03 «Заметки»): один компонент на подборе, в каталоге и во встречных
 * предложениях, чтобы платёж на разных экранах не расходился. Все числа приходят готовыми.
 */
export function VariantCard({
  id,
  title,
  headingLevel = 3,
  recommended = false,
  why,
  amountRub,
  termMonths,
  paymentRub,
  paymentKind,
  overpaymentRub,
  ratePercentFrom,
  approximate = false,
  decisionTime,
  documents = [],
  needsCollateral = false,
  needsContract = false,
  needsSecurity = false,
  comfortableOptions = [],
  note,
  actions,
}: VariantCardProps) {
  const headingId = `${id}-title`;
  const interestOnly = paymentKind === PaymentKind.INTEREST_ONLY;
  const needs: string[] = [];
  if (needsSecurity) needs.push(t.needsSecurity);
  else if (needsCollateral) needs.push(t.needsCollateral);
  if (needsContract) needs.push(t.needsContract);
  const otherTerms = comfortableOptions.filter((option) => option.termMonths !== termMonths);

  return (
    <Card
      withBorder
      padding="lg"
      component="article"
      aria-labelledby={headingId}
      data-testid="variant-card"
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Title order={headingLevel} size="h3" id={headingId}>
            {title}
          </Title>
          {recommended ? (
            <Badge size="lg" variant="filled">
              {t.recommendedBadge}
            </Badge>
          ) : null}
        </Group>

        {why ? (
          <Text>
            <Text span fw={600}>
              {t.whyHeading}:{' '}
            </Text>
            {why}
          </Text>
        ) : null}

        <Stack component="dl" gap="xs" m={0}>
          {amountRub != null ? <Row label={t.amount}>{formatMoney(amountRub)}</Row> : null}
          {termMonths != null ? <Row label={t.term}>{formatTermMonths(termMonths)}</Row> : null}
          <Row
            label={
              <>
                <TermHint hint={termHints.payment} label={t.payment} />
                {interestOnly ? ` (${t.paymentInterestOnly})` : ''}
              </>
            }
          >
            {paymentRub != null ? formatMoney(paymentRub) : t.paymentLater}
          </Row>
          {overpaymentRub != null ? (
            <Row label={<TermHint hint={termHints.overpayment} />}>
              {formatMoney(overpaymentRub)}
            </Row>
          ) : null}
          {ratePercentFrom != null ? (
            <Row label={<TermHint hint={termHints.rate} />}>
              {fill(t.rateFrom, { rate: formatPercent(ratePercentFrom) })}
            </Row>
          ) : null}
          {decisionTime ? (
            <Row label={t.decision}>
              {decisionTime === DecisionTime.AUTO ? t.decisionAuto : t.decisionManual}
            </Row>
          ) : null}
        </Stack>
        {ratePercentFrom != null && approximate ? (
          <Text size="sm" c="dimmed">
            {t.rateApproximate}
          </Text>
        ) : null}

        {needs.length > 0 ? (
          <List size="sm" spacing={2}>
            {needs.map((item) => (
              <List.Item key={item}>{item}</List.Item>
            ))}
          </List>
        ) : null}

        {documents.length > 0 ? (
          <Stack gap={4}>
            <Text fw={600}>{t.documentsHeading}</Text>
            <List size="sm" spacing={2}>
              {documents.map((document) => (
                <List.Item key={document}>{document}</List.Item>
              ))}
            </List>
          </Stack>
        ) : null}

        {otherTerms.length > 0 ? (
          <Stack gap={4}>
            <Text fw={600}>{t.comfortableHeading}</Text>
            <List size="sm" spacing={2} data-testid="comfortable-options">
              {otherTerms.map((option) => (
                <List.Item key={option.termMonths}>
                  {fill(t.comfortableLine, {
                    term: formatTermMonths(option.termMonths),
                    payment: formatMoney(option.paymentRub),
                    overpayment: formatMoney(option.overpaymentRub),
                  })}
                  {option.recommended ? ` (${t.fits})` : ''}
                </List.Item>
              ))}
            </List>
          </Stack>
        ) : null}

        {note}
        {actions}
      </Stack>
    </Card>
  );
}
