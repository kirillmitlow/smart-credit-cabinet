import type { ReactNode } from 'react';
import { Card, Stack, Text, Title } from '@mantine/core';
import type { ApplicationOut } from '@/api/generated/model';
import { outcomes } from '@/texts';
import { ContractSigning } from '@/features/offers/ContractSigning';
import { CounterOfferPanel } from './CounterOfferPanel';
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
 * со статусом). Одобрение, отказ и встречное предложение читают снимок решения сервера
 * (T-422, T-423); остальные исходы (T-424, T-425) пока короткие пояснения.
 */
export function OutcomeBlock({ application }: { application: ApplicationOut }) {
  switch (application.status) {
    case 'APPROVED':
      return <DecisionPanel application={application} />;
    case 'REJECTED':
      return <DecisionPanel application={application} />;
    case 'COUNTER_OFFER':
      return <CounterOfferPanel application={application} />;
    case 'NEEDS_INFO':
      return <NoticeBlock title={outcomes.needsInfo.title} body={outcomes.needsInfo.body} />;
    case 'MANUAL_REVIEW':
      return <NoticeBlock title={outcomes.manual.title} body={outcomes.manual.body} />;
    case 'OFFER_ACCEPTED':
    case 'SIGNED':
    case 'DISBURSING':
    case 'DISBURSED':
      return <ContractSigning applicationId={application.id} />;
    default:
      return null;
  }
}
