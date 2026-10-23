import { Alert, Button, Card, Group, List, Loader, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useGetApplicationDecision } from '@/api/generated/api';
import type { ApplicationOut, ClientDecisionOut } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { OfferActions } from '@/features/offers/OfferActions';
import { SchedulePreview } from './SchedulePreview';
import { formatDateTime, formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { decision as t, fill, outcomes } from '@/texts';

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" align="baseline">
      <Text c="dimmed">{label}</Text>
      <Text fw={600}>{value}</Text>
    </Group>
  );
}

function TextList({ heading, items }: { heading: string; items: string[] }) {
  return items.length ? (
    <Stack gap="xs">
      <Title order={3} size="h4">
        {heading}
      </Title>
      <List>
        {items.map((item, index) => (
          <List.Item key={`${index}:${item}`}>{item}</List.Item>
        ))}
      </List>
    </Stack>
  ) : null;
}

function Approved({ data, canAccept }: { data: ClientDecisionOut; canAccept: boolean }) {
  const terms = data.terms;
  if (!terms) return <Alert color="yellow">{t.noTerms}</Alert>;
  return (
    <>
      <Fact label={outcomes.approved.amount} value={formatMoney(terms.amountRub)} />
      <Fact label={outcomes.approved.term} value={formatTermMonths(terms.termMonths)} />
      <Fact label={t.rate} value={formatPercent(terms.ratePercent)} />
      <Fact label={t.payment} value={formatMoney(terms.paymentRub)} />
      {terms.lastPaymentRub !== terms.paymentRub ? (
        <Fact label={t.lastPayment} value={formatMoney(terms.lastPaymentRub)} />
      ) : null}
      <Fact label={t.overpayment} value={formatMoney(terms.overpaymentRub)} />
      {data.rateBreakdown.length ? (
        <details>
          <summary>{t.rateBreakdown}</summary>
          <Stack gap="xs" mt="xs">
            {data.rateBreakdown.map((part, index) => (
              <Fact
                key={`${index}:${part.label}`}
                label={part.label}
                value={formatPercent(part.percent)}
              />
            ))}
          </Stack>
        </details>
      ) : null}
      <TextList heading={t.helped} items={data.whatHelped} />
      <SchedulePreview terms={terms} />
      {data.offer ? (
        <Text size="sm">{fill(t.expires, { date: formatDateTime(data.offer.expiresAt) })}</Text>
      ) : null}
      <Text>{outcomes.approved.next}</Text>
      {data.offer && canAccept ? <OfferActions offer={data.offer} /> : null}
    </>
  );
}

/** Только числа и объяснения снимка сервера; правила и причины на клиенте не пересчитываются. */
export function DecisionPanel({ application }: { application: ApplicationOut }) {
  const query = useGetApplicationDecision(application.id, {
    query: { select: (response) => (response.status === 200 ? response.data : undefined) },
  });
  const data = query.data;
  const approved = application.status === 'APPROVED';
  const expected = approved ? 'APPROVED' : 'REJECTED';
  return (
    <Card withBorder padding="lg" component="section" aria-labelledby="outcome-title">
      <Stack gap="md">
        <Title order={2} size="h3" id="outcome-title">
          {approved ? outcomes.approved.title : outcomes.rejected.title}
        </Title>
        {query.isPending ? (
          <Group role="status">
            <Loader size="sm" />
            <Text>{t.loading}</Text>
          </Group>
        ) : null}
        {query.isError ? (
          <ProblemAlert
            error={query.error}
            onAction={() => {
              void query.refetch();
            }}
          />
        ) : null}
        {data && data.outcome !== expected ? <Alert color="yellow">{t.unavailable}</Alert> : null}
        {data?.outcome === expected ? (
          approved ? (
            <Approved
              data={data}
              canAccept={!query.isError && application.allowedActions.includes('ACCEPT_OFFER')}
            />
          ) : (
            <>
              <TextList
                heading={t.reasons}
                items={data.reasons.slice(0, 3).map((reason) => reason.text)}
              />
              <TextList heading={t.affected} items={data.whatAffected} />
              <TextList heading={outcomes.rejected.whatToDo} items={data.nextSteps} />
              <Group>
                <Button component={Link} to="/wizard">
                  {outcomes.rejected.pickOther}
                </Button>
                <Button component={Link} to="/" variant="light">
                  {outcomes.rejected.understood}
                </Button>
              </Group>
            </>
          )
        ) : null}
        {!query.isPending &&
        !query.isError &&
        (!data || data.outcome !== expected || (approved && !data.terms)) ? (
          <Button
            variant="light"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t.refresh}
          </Button>
        ) : null}
      </Stack>
    </Card>
  );
}
