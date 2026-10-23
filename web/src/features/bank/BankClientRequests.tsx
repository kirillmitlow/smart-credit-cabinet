import { Alert, Paper, Stack, Text, Title } from '@mantine/core';
import type { BankApplicationCard } from '@/api/generated/model';
import { formatDateTime } from '@/lib/format';
import { fill } from '@/texts';
import { bankActions as t } from '@/texts/bankActions';
import { bankLabel } from './bankFormatting';

export function BankClientRequests({ card }: { card: BankApplicationCard }) {
  return (
    <Paper withBorder p="md" data-testid="bank-client-requests">
      <Stack gap="sm">
        <Title order={2} size="h3">
          {t.requestsTitle}
        </Title>
        {card.latestAnsweredRound ? (
          <Alert color="blue">{fill(t.newAnswer, { round: card.latestAnsweredRound })}</Alert>
        ) : null}
        {!card.clientTasks?.length ? <Text>{t.noRequests}</Text> : null}
        {card.clientTasks?.map((task) => (
          <Paper withBorder p="sm" key={task.id}>
            <Stack gap={4}>
              <Title order={3} size="h5">
                {task.title}
              </Title>
              <Text size="sm">
                {fill(t.round, { round: task.round })} · {bankLabel(t.taskStatuses, task.status)}
              </Text>
              <Text size="sm">{task.whyText}</Text>
              {task.what ? <Text size="sm">{task.what}</Text> : null}
              {task.where ? <Text size="sm">{task.where}</Text> : null}
              {task.status === 'ANSWERED' ? (
                <>
                  <Text fw={600} size="sm">
                    {t.answer}
                  </Text>
                  <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                    {task.answer}
                  </Text>
                  <Text size="xs">
                    {t.answeredAt}: {formatDateTime(task.answeredAt)}
                  </Text>
                </>
              ) : task.status === 'OPEN' ? (
                <Text size="sm" c="dimmed">
                  {t.waiting}
                </Text>
              ) : null}
            </Stack>
          </Paper>
        ))}
      </Stack>
    </Paper>
  );
}
