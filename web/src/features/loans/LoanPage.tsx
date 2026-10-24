import { Anchor, Button, Center, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { Link, useParams } from 'react-router';
import { getGetContractDocumentUrl, useGetApplicationOffer, useGetLoan } from '@/api/generated/api';
import type { LoanDetail } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { resolveUrl } from '@/api/client';
import { ProblemAlert } from '@/components/ProblemAlert';
import { ErrorScreen } from '@/components/ErrorScreen';
import { formatDate, formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { errorView, fill, guards, loansTexts as t, productName } from '@/texts';
import { isLimitLoan, loanLimitOrAmount, repaymentOf } from './loanModel';
import { ScheduleTable } from './ScheduleTable';

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" wrap="nowrap" gap="lg">
      <Text c="dimmed">{label}</Text>
      <Text fw={600} ta="right">
        {value}
      </Text>
    </Group>
  );
}

/** Договор берём так же, как экран подписания: через предложение по заявке. Нет договора — нет ссылки */
function ContractLink({ applicationId }: { applicationId: string }) {
  const offer = useGetApplicationOffer(applicationId, {
    query: { select: (result) => (result.status === 200 ? result.data : undefined) },
  });
  const contractId = offer.data?.contractId;
  if (offer.isPending)
    return (
      <Text size="sm" role="status">
        {t.detail.documentLoading}
      </Text>
    );
  if (offer.error && !(isAppError(offer.error) && offer.error.status === 404)) {
    return <ProblemAlert error={offer.error} onAction={() => void offer.refetch()} />;
  }
  if (!contractId)
    return (
      <Stack gap="xs" align="flex-start">
        <Text size="sm">{t.detail.documentMissing}</Text>
        <Button variant="light" onClick={() => void offer.refetch()}>
          {t.detail.documentRefresh}
        </Button>
      </Stack>
    );
  return (
    <Anchor
      href={resolveUrl(getGetContractDocumentUrl(contractId))}
      target="_blank"
      rel="noopener noreferrer"
    >
      {t.detail.document}
    </Anchor>
  );
}

function Conditions({ loan }: { loan: LoanDetail }) {
  const limit = isLimitLoan(loan);
  const repayment = repaymentOf(loan);
  const bullet = loan.repaymentType === 'BULLET';
  return (
    <Stack gap="xs" maw={560} component="section" aria-labelledby="loan-conditions">
      <Title order={2} size="h3" id="loan-conditions">
        {t.detail.conditions}
      </Title>
      <Fact
        label={limit ? t.card.limit : t.card.amount}
        value={formatMoney(loanLimitOrAmount(loan))}
      />
      <Fact label={t.card.rate} value={formatPercent(Number(loan.ratePercent))} />
      <Fact label={t.card.term} value={formatTermMonths(loan.termMonths)} />
      {repayment ? <Fact label={t.detail.repaymentType} value={t.repayment[repayment]} /> : null}
      {limit ? null : (
        <>
          <Fact label={t.card.outstanding} value={formatMoney(loan.outstandingRub)} />
          <Fact
            label={bullet ? t.detail.interestPayment : t.detail.payment}
            value={formatMoney(loan.paymentRub)}
          />
          {bullet ? (
            <Fact label={t.detail.principalAtEnd} value={formatMoney(loan.amountRub)} />
          ) : null}
          <Fact
            label={t.card.nextPayment}
            value={
              loan.nextPayment
                ? fill(t.card.nextPaymentValue, {
                    amount: formatMoney(loan.nextPayment.totalRub),
                    date: formatDate(loan.nextPayment.dueDate),
                  })
                : t.card.noNextPayment
            }
          />
        </>
      )}
      <Fact label={t.detail.settlementAccount} value={loan.settlementAccount} />
      <Fact label={t.detail.loanAccount} value={loan.loanAccount} />
      <Fact label={t.detail.openedOn} value={formatDate(loan.openedOn)} />
    </Stack>
  );
}

function LoanView({ loan }: { loan: LoanDetail }) {
  const product = productName(loan.productCode);
  const heading = product ?? fill(t.card.number, { number: loan.contractNumber });
  const headingRef = usePageHeading(heading);
  const limit = isLimitLoan(loan);
  return (
    <Stack gap="lg">
      <Button component={Link} to="/loans" variant="subtle" px={0} style={{ alignSelf: 'start' }}>
        {t.detail.back}
      </Button>
      <Stack gap={2}>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {heading}
        </Title>
        <Text c="dimmed">{fill(t.card.number, { number: loan.contractNumber })}</Text>
      </Stack>
      <Conditions loan={loan} />
      <ContractLink applicationId={loan.applicationId} />
      {limit ? (
        <Text data-testid="loan-limit-note">{t.detail.limitNote}</Text>
      ) : (
        <Stack gap="sm" component="section" aria-labelledby="loan-schedule">
          <Title order={2} size="h3" id="loan-schedule">
            {t.detail.schedule}
          </Title>
          <ScheduleTable
            contractNumber={loan.contractNumber}
            schedule={loan.schedule}
            amountRub={loan.amountRub}
            nextSeq={loan.nextPayment?.seq ?? null}
          />
        </Stack>
      )}
      <Text size="sm" c="dimmed">
        {t.detail.notModelled}
      </Text>
    </Stack>
  );
}

/** Страница кредита (60-03 №15): условия, график платежей, «Скачать договор». Чужой кредит даёт `404` */
export function LoanPage() {
  const { id = '' } = useParams();
  const query = useGetLoan(id);
  const loan = query.data?.status === 200 ? query.data.data : undefined;

  if (query.isPending) {
    return (
      <Center py="xl" role="status">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t.loadingOne}
          </Text>
        </Stack>
      </Center>
    );
  }
  if (!loan) {
    if (isAppError(query.error) && query.error.status === 404) {
      return (
        <ErrorScreen
          title={t.notFound.title}
          body={t.notFound.body}
          actions={
            <Button component={Link} to="/loans" variant="light">
              {t.notFound.toList}
            </Button>
          }
        />
      );
    }
    const view = errorView(query.error);
    return (
      <ErrorScreen
        title={guards.generalError.title}
        body={view.text}
        requestId={view.requestId}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  return <LoanView loan={loan} />;
}
