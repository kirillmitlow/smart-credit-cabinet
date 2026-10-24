import { documentTexts as dt } from '@/texts/documents';
import { Alert, Anchor, Badge, Group, Paper, Stack, Text, Title } from '@mantine/core';
import type { BankApplicationCard, BankDocument } from '@/api/generated/model';
import { getDownloadDocumentUrl } from '@/api/generated/api';
import { resolveUrl } from '@/api/client';
import { formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { applicationStatusLabels } from '@/texts';
import { bankCard as t } from '@/texts/bank';
import { BankSnapshotData } from './BankSnapshotData';
import { bankLabel } from './bankFormatting';

function BankDocumentItem({ document }: { document: BankDocument }) {
  const pdf = document.mime === 'application/pdf';
  const download = resolveUrl(getDownloadDocumentUrl(document.id, { zone: 'bank' }));
  const preview = pdf
    ? resolveUrl(getDownloadDocumentUrl(document.id, { zone: 'bank', preview: true }))
    : download;
  return (
    <Paper withBorder p="sm">
      <Text size="xs" c="dimmed">
        {dt.kinds[document.kind] ?? dt.kinds.OTHER}
      </Text>
      <Anchor
        href={preview}
        target={pdf ? '_blank' : undefined}
        rel="noopener noreferrer"
        style={{ overflowWrap: 'anywhere' }}
      >
        {document.filename}
      </Anchor>
      {pdf ? <Text size="xs">{dt.openPdf}</Text> : null}
      <Text size="sm">
        {document.origin === 'SYSTEM_GENERATED'
          ? dt.generated
          : document.origin === 'DEMO_GENERATED'
            ? dt.demoGenerated
            : dt.uploaded}
        {' · '}
        {formatDateTime(document.createdAt)}
        {' · '}
        {dt.size(document.sizeBytes)}
      </Text>
      <Anchor size="sm" href={download} aria-label={`${dt.download}: ${document.filename}`}>
        {dt.download}
      </Anchor>
      {document.cancelledAt ? <Badge color="gray">{dt.replaced}</Badge> : null}
      {document.kind === 'BANK_STATEMENT_1C' ? (
        document.parseStatus === 'FAILED' ? (
          <Text size="sm" c="red.8" role="alert">
            {dt.parseErrors[document.parseError ?? ''] ?? dt.bankFailed}
          </Text>
        ) : document.parseStatus === 'PARSED' ? (
          <Stack gap={2}>
            <Text size="sm">{dt.bankParsed}</Text>
            <Text size="sm">
              {document.confirmedAt
                ? `${dt.bankConfirmed}: ${formatDateTime(document.confirmedAt)}`
                : dt.bankNotConfirmed}
            </Text>
          </Stack>
        ) : ['PENDING', 'PROCESSING'].includes(document.parseStatus) ? (
          <Text size="sm" role="status">
            {document.parseStatus === 'PROCESSING' ? dt.processing : dt.pending}
          </Text>
        ) : null
      ) : null}
      {pdf && document.origin !== 'SYSTEM_GENERATED' ? (
        <Text size="sm" mt="xs">
          {dt.pdfReview}
        </Text>
      ) : null}
      <details>
        <summary>{dt.hash}</summary>
        <Text size="xs" component="code" style={{ overflowWrap: 'anywhere' }}>
          {document.sha256}
        </Text>
      </details>
    </Paper>
  );
}

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
        {card.documents === null ? (
          <Text mt="sm">{t.documentsUnavailable}</Text>
        ) : card.documents.length === 0 ? (
          <Text mt="sm">{t.noDocuments}</Text>
        ) : (
          <Stack gap="sm" mt="sm">
            {card.documents.map((document) => (
              <BankDocumentItem key={document.id} document={document} />
            ))}
          </Stack>
        )}
      </Paper>
      <Paper withBorder p="md" data-testid="bank-collateral">
        <Title order={2} size="h3">
          {dt.collateralTitle}
        </Title>
        {card.collateral ? (
          <Stack gap="xs" mt="sm">
            <Text>{card.collateral.description}</Text>
            <Text>{dt.declaredValue(formatMoney(card.collateral.valueRub))}</Text>
            <Text size="sm" c="dimmed">
              {dt.collateralSource}
            </Text>
          </Stack>
        ) : (
          <Text mt="sm">{dt.noCollateral}</Text>
        )}
      </Paper>
    </>
  );
}
