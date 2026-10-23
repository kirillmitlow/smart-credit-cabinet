import type { ReactNode } from 'react';
import { Card, Stack, Text, Title } from '@mantine/core';
import type { ApplicationOut } from '@/api/generated/model';
import { outcomes } from '@/texts';
import { ContractSigning } from '@/features/offers/ContractSigning';
import { CounterOfferPanel } from './CounterOfferPanel';
import { DecisionPanel } from './DecisionPanel';
import { NeedsInfoPanel } from './NeedsInfoPanel';

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
 * (T-422, T-423), «Нужна информация» — задачи клиенту (T-424); остальные исходы (T-425) пока короткие пояснения.
 */
export function OutcomeBlock({
  application,
  onTasksSent,
}: {
  application: ApplicationOut;
  /** Клиент отправил ответы банку (T-424): страница покажет «Проверяем заново» */
  onTasksSent?: () => void;
}) {
  switch (application.status) {
    case 'APPROVED':
      return <DecisionPanel application={application} />;
    case 'REJECTED':
      return <DecisionPanel application={application} />;
    case 'COUNTER_OFFER':
      return <CounterOfferPanel application={application} />;
    case 'NEEDS_INFO':
      return <NeedsInfoPanel application={application} onSent={onTasksSent} />;
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
