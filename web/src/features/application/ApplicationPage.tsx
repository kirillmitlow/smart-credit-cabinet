import { Alert, Anchor, Button, Center, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useState } from 'react';
import { Link, Navigate, useParams } from 'react-router';
import { isAppError } from '@/api/errors';
import { tokens } from '@/app/theme';
import { ErrorScreen } from '@/components/ErrorScreen';
import { PageHero } from '@/components/PageHero';
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
  const closed = application.status === 'WITHDRAWN' || application.status === 'EXPIRED';

  const muted = tokens.header.muted;

  return (
    <Stack gap="lg">
      <PageHero>
        <Stack gap="lg">
          <Anchor
            component={Link}
            to="/"
            fw={600}
            underline="never"
            style={{ color: tokens.header.color, alignSelf: 'flex-start' }}
          >
            <span aria-hidden="true">← </span>
            {shell.common.toHome}
          </Anchor>
          <Stack gap={6}>
            <Title order={1} ref={headingRef} tabIndex={-1} c="inherit">
              {fill(applicationPage.title, { number })}
            </Title>
            <Text fz={18} className="scc-num" style={{ color: '#e4e4e7', whiteSpace: 'normal' }}>
              {summary}
            </Text>
            {isInFlight(application.status) ? (
              <Text size="sm" style={{ color: muted }}>
                {applicationPage.autoUpdate}
              </Text>
            ) : null}
          </Stack>
          <div role="status" aria-live="polite" data-testid="timeline-live">
            {timeline.current ? (
              <Text fw={600} style={{ color: tokens.accentOnDark }}>
                {applicationPage.nowLabel}: {timeline.current.title}
                {timeline.current.text ? `. ${timeline.current.text}` : ''}
              </Text>
            ) : null}
            {timeline.note ? (
              <Text fw={600} c="inherit">
                {timeline.note}
              </Text>
            ) : null}
          </div>
          {timelineQuery.isError ? (
            <Alert color="yellow" role="status" data-testid="timeline-unavailable">
              <Group justify="space-between">
                <Text size="sm">{timelineProgress.unavailable}</Text>
                <Button
                  size="compact-sm"
                  variant="light"
                  onClick={() => void timelineQuery.refetch()}
                >
                  {shell.common.retry}
                </Button>
              </Group>
            </Alert>
          ) : null}
          <Timeline model={timeline} />
        </Stack>
      </PageHero>

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

      <OutcomeBlock
        application={application}
        onTasksSent={() => {
          setAnswersSent(true);
        }}
      />

      {closed ? (
        <Group>
          <Button component={Link} to="/wizard">
            {applicationPage.closed.newApplication}
          </Button>
        </Group>
      ) : null}

      {canWithdraw ? (
        <Group justify="flex-end">
          <WithdrawButton application={application} asDecline={isOffer} />
        </Group>
      ) : null}
    </Stack>
  );
}
