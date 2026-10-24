import { Alert, Button, Center, Grid, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useState } from 'react';
import { Link, Navigate, useParams } from 'react-router';
import { isAppError } from '@/api/errors';
import { ErrorScreen } from '@/components/ErrorScreen';
import { NotFoundScreen } from '@/app/screens';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import {
  applicationPage,
  clientTasks,
  errorView,
  fill,
  guards,
  productName,
  shell,
  timelineProgress,
} from '@/texts';
import { OutcomeBlock } from './OutcomeBlock';
import { isInFlight } from './statuses';
import { Timeline } from './Timeline';
import { buildTimeline, timelineFromEvents } from './timelineModel';
import { useApplication } from './useApplication';
import { useTimeline } from './useTimeline';
import { WithdrawButton } from './WithdrawButton';

/**
 * Страница заявки (60-03 №8): слева таймлайн из шести шагов, справа блок исхода по статусу,
 * внизу «Отозвать». Пока нет живых событий, страница сама спрашивает сервер (см. `useApplication`).
 */
export function ApplicationPage() {
  const { id = '' } = useParams();
  const query = useApplication(id);
  const application = query.data;
  const timelineQuery = useTimeline(application);
  const number = application?.number ?? '';
  // Клиент только что отправил ответы банку: пока идёт новая проверка, говорим об этом прямо
  const [answersSent, setAnswersSent] = useState(false);
  const headingRef = usePageHeading(
    application ? fill(applicationPage.title, { number }) : applicationPage.loading,
  );

  if (query.isPending) {
    return (
      <Center py="xl" role="status">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {applicationPage.loading}
          </Text>
        </Stack>
      </Center>
    );
  }
  if (!application) {
    if (isAppError(query.error) && query.error.status === 404) {
      return <NotFoundScreen kind="application" />;
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
  if (application.status === 'DRAFT') {
    return <Navigate to={`/applications/${application.id}/edit/1`} replace />;
  }

  const timeline =
    timelineQuery.data?.version === application.version
      ? timelineFromEvents(timelineQuery.data)
      : buildTimeline({
          status: application.status,
          submittedAt: application.submittedAt,
          amountRub: application.amountRub,
        });
  const product = productName(application.productCode);
  const summary =
    application.amountRub !== null && application.termMonths !== null
      ? fill(product ? applicationPage.summaryWithProduct : applicationPage.summary, {
          product: product ?? '',
          amount: formatMoney(application.amountRub),
          term: formatTermMonths(application.termMonths),
        })
      : applicationPage.summaryEmpty;
  const canWithdraw = application.allowedActions.includes('WITHDRAW');
  const isOffer = application.status === 'APPROVED' || application.status === 'COUNTER_OFFER';
  // Три карточки встречного предложения не помещаются в половину страницы
  const wide = application.status === 'COUNTER_OFFER';
  const closed = application.status === 'WITHDRAWN' || application.status === 'EXPIRED';

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {fill(applicationPage.title, { number })}
        </Title>
        <Text size="lg">{summary}</Text>
        {isInFlight(application.status) ? (
          <Text size="sm" c="dimmed">
            {applicationPage.autoUpdate}
          </Text>
        ) : null}
      </Stack>

      {query.isError ? (
        <Alert color="yellow" role="status" data-testid="lost-connection">
          <Group justify="space-between">
            <Text>{applicationPage.lostConnection}</Text>
            <Button
              size="compact-sm"
              variant="light"
              onClick={() => {
                void query.refetch();
              }}
            >
              {errorView(query.error).action ?? shell.common.retry}
            </Button>
          </Group>
        </Alert>
      ) : null}

      {answersSent && application.status === 'CHECKING' ? (
        <Alert color="green" role="status" title={clientTasks.sentTitle} data-testid="recheck-note">
          {clientTasks.sent}
        </Alert>
      ) : null}

      <div role="status" aria-live="polite" data-testid="timeline-live">
        {timeline.current ? (
          <Text fw={600}>
            {applicationPage.nowLabel}: {timeline.current.title}
            {timeline.current.text ? `. ${timeline.current.text}` : ''}
          </Text>
        ) : null}
        {timeline.note ? <Text fw={600}>{timeline.note}</Text> : null}
      </div>

      <Grid gap="xl">
        <Grid.Col span={{ base: 12, md: wide ? 12 : 6 }}>
          {timelineQuery.isError ? (
            <Alert color="yellow" role="status" mb="md" data-testid="timeline-unavailable">
              <Stack gap="xs">
                <Text size="sm">{timelineProgress.unavailable}</Text>
                <Button
                  size="compact-sm"
                  variant="light"
                  onClick={() => void timelineQuery.refetch()}
                >
                  {shell.common.retry}
                </Button>
              </Stack>
            </Alert>
          ) : null}
          <Timeline model={timeline} />
          {closed ? (
            <Group mt="md">
              <Button component={Link} to="/wizard">
                {applicationPage.closed.newApplication}
              </Button>
            </Group>
          ) : null}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: wide ? 12 : 6 }}>
          <OutcomeBlock
            application={application}
            onTasksSent={() => {
              setAnswersSent(true);
            }}
          />
        </Grid.Col>
      </Grid>

      {canWithdraw ? (
        <Group>
          <WithdrawButton application={application} asDecline={isOffer} />
        </Group>
      ) : null}
    </Stack>
  );
}
