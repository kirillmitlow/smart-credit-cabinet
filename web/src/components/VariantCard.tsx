import type { CSSProperties, ReactNode } from 'react';
import { Badge, Box, Card, Group, List, Stack, Text, Title } from '@mantine/core';
import { brandPalette, fonts, graphitePalette, tokens } from '@/app/theme';
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
  /** Ставка окончательная (решение банка): без слова «от» */
  rateExact?: boolean;
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
    <Group
      justify="space-between"
      wrap="nowrap"
      align="baseline"
      gap="md"
      py={10}
      style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}
    >
      <Text component="dt" c="dimmed">
        {label}
      </Text>
      <Text component="dd" m={0} fw={600} ta="right" className="scc-num">
        {children}
      </Text>
    </Group>
  );
}

/** Рекомендуемая карточка тёмная (D-113): переопределяем переменные цвета внутри неё */
const darkCardVars = {
  '--mantine-color-text': '#ffffff',
  '--mantine-color-dimmed': tokens.header.muted,
  '--mantine-color-default-border': graphitePalette[7],
  '--mantine-color-anchor': tokens.accentOnDark,
  '--mantine-color-body': graphitePalette[9],
} as CSSProperties;

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
  rateExact = false,
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
      padding={28}
      component="article"
      aria-labelledby={headingId}
      data-testid="variant-card"
      data-recommended={recommended || undefined}
      h="100%"
      bg={recommended ? 'graphite.9' : undefined}
      c={recommended ? 'white' : undefined}
      style={
        recommended
          ? { ...darkCardVars, boxShadow: `inset 0 0 0 3px ${brandPalette[6]}` }
          : undefined
      }
    >
      <Stack gap="md" h="100%">
        {recommended ? (
          <Badge
            size="lg"
            radius="xl"
            tt="none"
            variant="filled"
            style={{ alignSelf: 'flex-start' }}
          >
            {t.recommendedBadge}
          </Badge>
        ) : null}
        <Title order={headingLevel} size="h3" id={headingId} c="inherit">
          {title}
        </Title>
        {amountRub != null ? (
          <Stack gap={4}>
            <Text ff={fonts.display} fw={700} fz={30} lh={1.15} className="scc-num" c="inherit">
              {formatMoney(amountRub)}
            </Text>
            {paymentRub != null ? (
              <Stack gap={0}>
                <Text size="sm" c="dimmed">
                  <TermHint hint={termHints.payment} label={t.payment} />
                  {interestOnly ? ` (${t.paymentInterestOnly})` : ''}
                </Text>
                <Text
                  ff={fonts.display}
                  fw={700}
                  fz={20}
                  className="scc-num"
                  style={{ color: recommended ? tokens.accentOnDark : undefined }}
                >
                  {formatMoney(paymentRub)}
                </Text>
              </Stack>
            ) : null}
          </Stack>
        ) : null}

        {why ? (
          <Text>
            <Text span fw={600}>
              {t.whyHeading}:{' '}
            </Text>
            {why}
          </Text>
        ) : null}

        <Stack component="dl" gap={0} m={0}>
          {termMonths != null ? <Row label={t.term}>{formatTermMonths(termMonths)}</Row> : null}
          {amountRub == null || paymentRub == null ? (
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
          ) : null}
          {overpaymentRub != null ? (
            <Row label={<TermHint hint={termHints.overpayment} />}>
              {formatMoney(overpaymentRub)}
            </Row>
          ) : null}
          {ratePercentFrom != null ? (
            <Row label={<TermHint hint={termHints.rate} />}>
              {rateExact
                ? formatPercent(ratePercentFrom)
                : fill(t.rateFrom, { rate: formatPercent(ratePercentFrom) })}
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
        {actions ? <Box mt="auto">{actions}</Box> : null}
      </Stack>
    </Card>
  );
}
