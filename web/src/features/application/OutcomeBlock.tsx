import type { ReactNode } from 'react';
import { Card, Stack, Text, Title } from '@mantine/core';
import type { ApplicationOut } from '@/api/generated/model';
import { outcomes } from '@/texts';
import { DecisionPanel } from './DecisionPanel';

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

function NoticeBlock({ title, body }: { title: string; body: string }) {
  return (
    <OutcomeCard title={title}>
      <Text>{body}</Text>
    </OutcomeCard>
  );
}

/**
 * Блок исхода выбирается по `status` (60-01: одна страница на все статусы, адрес не расходится
 * со статусом). Одобрение и отказ читают снимок решения сервера (T-422); остальные исходы
 * (T-423…T-425) пока короткие пояснения.
 */
export function OutcomeBlock({ application }: { application: ApplicationOut }) {
  switch (application.status) {
    case 'APPROVED':
      return <DecisionPanel application={application} />;
    case 'REJECTED':
      return <DecisionPanel application={application} />;
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
