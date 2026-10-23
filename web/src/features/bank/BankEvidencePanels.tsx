import { Alert, Anchor, Badge, Group, Paper, Stack, Text, Title } from '@mantine/core';
import type { BankApplicationCard } from '@/api/generated/model';
import { formatDate, formatDateTime } from '@/lib/format';
import { applicationStatusLabels } from '@/texts';
import { bankCard as t } from '@/texts/bank';
import { BankSnapshotData } from './BankSnapshotData';
import { bankLabel } from './bankFormatting';

export function BankEvidencePanels({ card }: { card: BankApplicationCard }) {
  return (
    <>
      <Paper withBorder p="md" data-testid="bank-sources">
        <Title order={2} size="h3">
          {t.sources}
        </Title>
        {!card.sourceSnapshots.length ? (
          <Text mt="sm">{t.noSources}</Text>
        ) : (
          <Stack gap="sm" mt="sm">
            {card.sourceSnapshots.map((source) => (
              <Paper key={source.id} withBorder p="sm">
                <Group justify="space-between">
                  <Title order={3} size="h5">
                    {bankLabel(t.sourceNames, source.resource)}
                  </Title>
                  <Badge
                    c="dark.9"
                    variant="light"
                    color={source.status === 'UNAVAILABLE' ? 'red' : 'gray'}
                  >
                    {bankLabel(t.sourceStatus, source.status)}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  {source.subjectInn} · {source.usedByCurrentDecision ? t.used : t.earlierSource}
                </Text>
                <Text size="sm">
                  {t.actualAt}: {formatDate(source.dataActualAt)}
                </Text>
                <Text size="sm">
                  {t.retrievedAt}: {formatDateTime(source.retrievedAt)}
                </Text>
                <Text size="xs" style={{ overflowWrap: 'anywhere' }}>
                  {t.requestId}: {source.requestId ?? t.noData}
                </Text>
                {source.status === 'UNAVAILABLE' ? (
                  <Stack gap={4} mt="sm">
                    {card.status === 'MANUAL_REVIEW' && !card.stale ? (
                      <Anchor href="#bank-actions">{t.recheck}</Anchor>
                    ) : (
                      <Text size="xs">{t.recheckUnavailable}</Text>
                    )}
                  </Stack>
                ) : (
                  <details>
                    <summary>{t.original}</summary>
                    <BankSnapshotData value={source.payload} />
                  </details>
                )}
              </Paper>
            ))}
          </Stack>
        )}
      </Paper>
      <Paper withBorder p="md" data-testid="bank-history">
        <Title order={2} size="h3">
          {t.history}
        </Title>
        {!card.history.length ? (
          <Text mt="sm">{t.noHistory}</Text>
        ) : (
          <Stack component="ol" gap="sm" mt="sm">
            {card.history.map((entry) => (
              <li key={entry.id}>
                <Text size="sm" fw={500}>
                  {bankLabel(t.eventKinds, entry.kind)}
                </Text>
                <Text size="xs" c="dimmed">
                  {formatDateTime(entry.at)} ·{' '}
                  {entry.actorName ?? bankLabel(t.actors, entry.actorType)}
                </Text>
                {entry.toStatus ? (
                  <Text size="sm">
                    {entry.fromStatus
                      ? `${bankLabel(applicationStatusLabels, entry.fromStatus)} → `
                      : ''}
                    {bankLabel(applicationStatusLabels, entry.toStatus)}
                  </Text>
                ) : null}
                {entry.reasonCode ? <Text size="xs">{entry.reasonCode}</Text> : null}
                {Object.keys(entry.payload).length ? (
                  <details>
                    <summary>{t.original}</summary>
                    <BankSnapshotData value={entry.payload} />
                  </details>
                ) : null}
              </li>
            ))}
          </Stack>
        )}
        <Title order={3} size="h4" mt="md">
          {t.previous}
        </Title>
        <Stack gap="sm" mt="xs">
          {card.decisions.map((decision) => (
            <Paper key={decision.id} withBorder p="sm">
              <Text fw={500} size="sm">
                {decision.source === 'ENGINE' ? t.engineSource : t.underwriterSource} ·{' '}
                {decision.outcome}
              </Text>
              <Text size="xs">
                {formatDateTime(decision.createdAt)} · {t.policy}: {decision.policy.version} ·{' '}
                {t.engine}: {decision.engineVersion}
              </Text>
              {decision.overrideReason ? (
                <Alert color="gray" mt="xs">
                  <Text size="xs" fw={600}>
                    {t.internalNote}
                  </Text>
                  <Text size="sm">{decision.overrideReason}</Text>
                </Alert>
              ) : null}
            </Paper>
          ))}
        </Stack>
      </Paper>
      <Paper withBorder p="md" data-testid="bank-documents">
        <Title order={2} size="h3">
          {t.documents}
        </Title>
        <Text mt="sm">
          {card.documents === null
            ? t.documentsUnavailable
            : card.documents.length
              ? t.documentsPreviewUnavailable
              : t.noDocuments}
        </Text>
      </Paper>
    </>
  );
}
