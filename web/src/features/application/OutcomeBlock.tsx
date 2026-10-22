import type { ReactNode } from 'react';
import { Button, Card, Group, List, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import type { ApplicationOut } from '@/api/generated/model';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { outcomes } from '@/texts';

function OutcomeCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card withBorder padding="lg" component="section" aria-labelledby="outcome-title">
      <Stack gap="sm">
        <Title order={2} size="h3" id="outcome-title">
          {title}
        </Title>
        {children}
      </Stack>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <Text c="dimmed">{label}</Text>
      <Text fw={600}>{value}</Text>
    </Group>
  );
}

/** «Одобрено» (60-03 №9): условия из заявки; ставка и платёж придут вместе с деталями решения (T-259) */
function ApprovedBlock({ application }: { application: ApplicationOut }) {
  return (
    <OutcomeCard title={outcomes.approved.title}>
      <Fact label={outcomes.approved.amount} value={formatMoney(application.amountRub)} />
      <Fact label={outcomes.approved.term} value={formatTermMonths(application.termMonths)} />
      <Text>{outcomes.approved.next}</Text>
      <Text size="sm" c="dimmed">
        {outcomes.approved.detailsLater}
      </Text>
      <Group>
        <Button disabled aria-describedby="accept-later">
          {outcomes.approved.accept}
        </Button>
      </Group>
      <Text id="accept-later" size="sm" c="dimmed">
        {outcomes.approved.acceptLater}
      </Text>
    </OutcomeCard>
  );
}

/** «Отказ» (60-03 №13): спокойный тон; причины приходят из снимка решения, клиентский код их не собирает */
function RejectedBlock() {
  return (
    <OutcomeCard title={outcomes.rejected.title}>
      <Text>{outcomes.rejected.body}</Text>
      <Title order={3} size="h4">
        {outcomes.rejected.whatToDo}
      </Title>
      <List>
        {outcomes.rejected.steps.map((step) => (
          <List.Item key={step}>{step}</List.Item>
        ))}
      </List>
      <Group>
        <Button component={Link} to="/wizard">
          {outcomes.rejected.pickOther}
        </Button>
        <Button component={Link} to="/" variant="light">
          {outcomes.rejected.understood}
        </Button>
      </Group>
    </OutcomeCard>
  );
}

function NoticeBlock({ title, body }: { title: string; body: string }) {
  return (
    <OutcomeCard title={title}>
      <Text>{body}</Text>
    </OutcomeCard>
  );
}

/**
 * Блок исхода выбирается по `status` (60-01: одна страница на все статусы, адрес не расходится
 * со статусом). Здесь только заглушки «Одобрено» и «Отказ» (T-422); остальные исходы
 * (T-423…T-425) пока короткие пояснения.
 */
export function OutcomeBlock({ application }: { application: ApplicationOut }) {
  switch (application.status) {
    case 'APPROVED':
      return <ApprovedBlock application={application} />;
    case 'REJECTED':
      return <RejectedBlock />;
    case 'COUNTER_OFFER':
      return <NoticeBlock title={outcomes.counter.title} body={outcomes.counter.body} />;
    case 'NEEDS_INFO':
      return <NoticeBlock title={outcomes.needsInfo.title} body={outcomes.needsInfo.body} />;
    case 'MANUAL_REVIEW':
      return <NoticeBlock title={outcomes.manual.title} body={outcomes.manual.body} />;
    case 'OFFER_ACCEPTED':
      return <NoticeBlock title={outcomes.signing.title} body={outcomes.signing.body} />;
    default:
      return null;
  }
}
