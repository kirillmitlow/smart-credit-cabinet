import { documentTexts as dt } from '@/texts/documents';
import { useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetApplicationQueryKey,
  getListApplicationTasksQueryKey,
  useAnswerTask,
  useSubmitTaskRound,
} from '@/api/generated/api';
import type { ApplicationOut, TaskOut } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { formatDate } from '@/lib/format';
import { clientTasks as t, fill, outcomes } from '@/texts';
import {
  assigneeKind,
  canSubmitRound,
  detailText,
  fieldText,
  isDirty,
  isSaved,
  roundView,
  type Edits,
  type RoundView,
} from './tasksModel';
import { putTask, putTaskList, useApplicationTasks } from './useTasks';
import { DocumentFiles } from './DocumentFiles';

const MAX_ANSWER = 4000;

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Text>
      <Text span fw={600}>
        {label}:
      </Text>{' '}
      {value}
    </Text>
  );
}

interface TaskItemProps {
  task: TaskOut;
  edits: Edits;
  locked: boolean;
  onEdit: (taskId: string, text: string) => void;
}

function TaskItem({ task, edits, locked, onEdit }: TaskItemProps) {
  const what = detailText(task, 'what');
  const where = detailText(task, 'where');
  const open = task.status === 'OPEN';
  const closedLabel = Object.hasOwn(t.status, task.status)
    ? t.status[task.status as keyof typeof t.status]
    : null;
  const titleId = `task-title-${task.id}`;
  const text = fieldText(task, edits);
  const saved = isSaved(task, edits);
  return (
    <Paper component="section" withBorder p="md" aria-labelledby={titleId} data-testid="info-task">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Title order={3} size="h4" id={titleId}>
            {task.title}
          </Title>
          {closedLabel ? (
            <Badge variant="light" color={task.status === 'ANSWERED' ? 'green' : 'gray'}>
              {closedLabel}
            </Badge>
          ) : null}
        </Group>
        <Fact label={t.why} value={task.whyText} />
        {what ? <Fact label={t.what} value={what} /> : null}
        {where ? <Fact label={t.where} value={where} /> : null}
        <Fact
          label={t.deadline}
          value={
            task.expiresAt
              ? fill(t.deadlineUntil, { date: formatDate(task.expiresAt) })
              : t.deadlineNone
          }
        />
        <Fact label={t.assignee} value={t.assignees[assigneeKind(task)]} />

        {open && task.canAnswer ? (
          <Stack gap={4}>
            <Textarea
              label={fill(t.answerLabel, { title: task.title })}
              description={task.kind === 'DOCUMENT' ? dt.answerHelp : undefined}
              placeholder={t.answerPlaceholder}
              value={text}
              maxLength={MAX_ANSWER}
              rows={4}
              resize="vertical"
              readOnly={locked}
              onChange={(event) => {
                onEdit(task.id, event.currentTarget.value);
              }}
            />
            {task.kind === 'DOCUMENT' ? (
              <DocumentFiles
                applicationId={task.applicationId}
                taskId={task.id}
                disabled={locked}
                onUploaded={(file) => onEdit(task.id, dt.uploadedAnswer(file.filename))}
              />
            ) : null}
            {saved ? (
              <Text size="sm" c="green.9">
                {t.draftSaved}
              </Text>
            ) : text.trim() !== '' ? (
              <Text size="sm" c="dimmed">
                {t.draftDirty}
              </Text>
            ) : null}
          </Stack>
        ) : null}
        {open && !task.canAnswer ? (
          <Stack gap={4}>
            <Text size="sm" c="dimmed">
              {t.notYours}
            </Text>
            {task.draftAnswer ? (
              <Text style={{ whiteSpace: 'pre-wrap' }}>
                <Text span fw={600}>
                  {t.othersAnswer}:
                </Text>{' '}
                {task.draftAnswer}
              </Text>
            ) : (
              <Text size="sm">{t.waitingAnswer}</Text>
            )}
          </Stack>
        ) : null}
        {task.status === 'ANSWERED' && task.answer ? (
          <Text style={{ whiteSpace: 'pre-wrap' }}>
            <Text span fw={600}>
              {t.yourAnswerSent}:
            </Text>{' '}
            {task.answer}
          </Text>
        ) : null}
      </Stack>
    </Paper>
  );
}

function SentNotice() {
  return (
    <Alert color="green" role="status" title={t.sentTitle}>
      {t.sent}
    </Alert>
  );
}

function submitHint(view: RoundView, ready: boolean): string | null {
  if (ready) return null;
  return view.othersMissing.length > 0 ? t.waitingOthers : t.needAll;
}

export interface NeedsInfoPanelProps {
  application: ApplicationOut;
  /** Ответы ушли банку: страница покажет «Проверяем заново» */
  onSent?: () => void;
}

/**
 * Блок «Нужна информация» (60-03 №11, 20-03): задачи текущего раунда с полем текста на каждую,
 * черновик, загрузка файлов для DOCUMENT и «Отправить ответы».
 * Двойное нажатие даёт один запрос: пока идёт работа, повторные нажатия игнорируются.
 */
export function NeedsInfoPanel({ application, onSent }: NeedsInfoPanelProps) {
  const client = useQueryClient();
  const { role } = useActiveCompany();
  const guarantor = role === 'GUARANTOR';
  const query = useApplicationTasks(application.id);
  const answer = useAnswerTask();
  const submit = useSubmitTaskRound();
  const [edits, setEdits] = useState<Edits>({});
  const [busy, setBusy] = useState<'save' | 'submit' | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);
  const lock = useRef(false);

  const list = query.data;
  const view = list ? roundView(list) : null;
  const ready = view ? canSubmitRound(view, edits) : false;
  const anyDirty = view ? view.mine.some((task) => isDirty(task, edits)) : false;

  const refreshAll = () => {
    void client.invalidateQueries({ queryKey: getListApplicationTasksQueryKey(application.id) });
    void client.invalidateQueries({ queryKey: getGetApplicationQueryKey(application.id) });
  };

  const run = async (kind: 'save' | 'submit', work: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(kind);
    setError(null);
    try {
      await work();
    } catch (failure) {
      setError(failure);
      // 409: раунд уже ушёл или задачу закрыли — экран должен показать, как есть на самом деле
      if (isAppError(failure) && failure.status === 409) refreshAll();
    } finally {
      lock.current = false;
      setBusy(null);
    }
  };

  const saveDirty = async (current: RoundView) => {
    for (const task of current.mine) {
      if (!isDirty(task, edits)) continue;
      const response = await answer.mutateAsync({
        taskId: task.id,
        data: { text: fieldText(task, edits).trim(), submitRound: false },
      });
      if (response.status !== 200) continue;
      putTask(client, application.id, response.data);
      setEdits((previous) => {
        const next = { ...previous };
        delete next[task.id];
        return next;
      });
    }
  };

  const onSave = () => {
    if (!view) return;
    void run('save', () => saveDirty(view));
  };

  const onSubmit = () => {
    if (!view || !ready) return;
    void run('submit', async () => {
      await saveDirty(view);
      const response = await submit.mutateAsync({ applicationId: application.id });
      if (response.status !== 200) return;
      putTaskList(client, application.id, response.data);
      setSent(true);
      onSent?.();
      void client.invalidateQueries({ queryKey: getGetApplicationQueryKey(application.id) });
      void client.invalidateQueries({ queryKey: ['/applications'] });
    });
  };

  const hint = view ? submitHint(view, ready) : null;
  const locked = busy !== null;

  return (
    <Card withBorder padding="lg" component="section" aria-labelledby="outcome-title">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Title order={2} size="h3" id="outcome-title">
            {outcomes.needsInfo.title}
          </Title>
          {list && list.currentRound > 0 ? (
            <Badge variant="light" color="red" size="lg">
              {fill(t.round, { round: list.currentRound, limit: list.roundsLimit })}
            </Badge>
          ) : null}
        </Group>

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

        {view && (sent || view.sent) ? <SentNotice /> : null}
        {view && view.tasks.length === 0 ? <Alert color="yellow">{t.preparing}</Alert> : null}

        {view && view.tasks.length > 0 && !sent && !view.sent ? (
          <>
            <Text>{t.intro}</Text>
            <Stack
              component="ul"
              gap="md"
              p={0}
              m={0}
              aria-label={t.listLabel}
              style={{ listStyle: 'none' }}
            >
              {view.tasks.map((task) => (
                <li key={task.id}>
                  <TaskItem
                    task={task}
                    edits={edits}
                    locked={locked}
                    onEdit={(taskId, text) => {
                      setEdits((previous) => ({ ...previous, [taskId]: text }));
                    }}
                  />
                </li>
              ))}
            </Stack>

            {error ? (
              <ProblemAlert
                error={error}
                onAction={() => {
                  setError(null);
                  refreshAll();
                }}
              />
            ) : null}

            {guarantor ? (
              <Stack gap="xs">
                <Text size="sm">{t.guarantorNote}</Text>
                <Group>
                  <Button
                    onClick={onSave}
                    disabled={!anyDirty}
                    loading={busy === 'save'}
                    loaderProps={{ 'aria-label': t.saving }}
                  >
                    {t.saveAnswer}
                  </Button>
                </Group>
              </Stack>
            ) : (
              <Stack gap="xs">
                <Group>
                  <Button
                    onClick={onSubmit}
                    disabled={!ready || locked}
                    loading={busy === 'submit'}
                    loaderProps={{ 'aria-label': t.submitting }}
                    aria-describedby="tasks-submit-hint"
                  >
                    {t.submit}
                  </Button>
                  <Button
                    variant="light"
                    onClick={onSave}
                    disabled={!anyDirty || locked}
                    loading={busy === 'save'}
                    loaderProps={{ 'aria-label': t.saving }}
                  >
                    {t.saveDraft}
                  </Button>
                </Group>
                <Text size="sm" c="dimmed" id="tasks-submit-hint">
                  {hint ?? t.draftNote}
                </Text>
              </Stack>
            )}
          </>
        ) : null}
      </Stack>
    </Card>
  );
}
