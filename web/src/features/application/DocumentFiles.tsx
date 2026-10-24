import { documentTexts as dt } from '@/texts/documents';
import { useRef, useState } from 'react';
import { Anchor, Button, FileInput, Group, Loader, Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getDownloadDocumentUrl,
  getListDocumentsQueryKey,
  useListDocuments,
  useUploadDocument,
} from '@/api/generated/api';
import { UploadDocumentBodyKind, type DocumentOut } from '@/api/generated/model';
import { resolveUrl } from '@/api/client';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { StatementConfirmation } from './StatementConfirmation';

const uploadKind = (kind: string) =>
  Object.values(UploadDocumentBodyKind).find((value) => value === kind);

function ParseStatus({ document }: { document: DocumentOut }) {
  if (document.parseStatus === 'FAILED') {
    return (
      <Text size="sm" c="red.8" role="alert">
        {dt.parseErrors[document.parseError ?? ''] ?? dt.parseFailed}
      </Text>
    );
  }
  if (['PENDING', 'PROCESSING'].includes(document.parseStatus)) {
    return (
      <Group gap="xs" role="status">
        <Loader size="xs" />
        <Text size="sm">{document.parseStatus === 'PROCESSING' ? dt.processing : dt.pending}</Text>
      </Group>
    );
  }
  if (document.parseStatus === 'PARSED') {
    const period = document.parsed?.period;
    const dates = period && typeof period === 'object' ? (period as Record<string, unknown>) : null;
    return (
      <Stack gap={2} role="status">
        <Text size="sm">{dt.parsed}</Text>
        {typeof dates?.start === 'string' && typeof dates.end === 'string' ? (
          <Text size="xs">{dt.period(dates.start, dates.end)}</Text>
        ) : null}
        <Text size="xs" c="dimmed">
          {dt.parsedHelp}
        </Text>
      </Stack>
    );
  }
  return (
    <Text size="xs" c="dimmed">
      {dt.saved}
    </Text>
  );
}

export function DocumentFiles({
  applicationId,
  taskId,
  disabled = false,
  onUploaded,
  includeUnassignedStatements = false,
}: {
  applicationId: string;
  taskId?: string;
  disabled?: boolean;
  onUploaded?: (file: DocumentOut) => void;
  includeUnassignedStatements?: boolean;
}) {
  const client = useQueryClient();
  const query = useListDocuments(
    { applicationId },
    {
      query: {
        refetchInterval: (state) => {
          const response = state.state.data;
          return response?.status === 200 &&
            response.data.some(
              (d) => !d.cancelledAt && ['PENDING', 'PROCESSING'].includes(d.parseStatus),
            )
            ? 1500
            : false;
        },
      },
    },
  );
  const action = useActionKey();
  const upload = useUploadDocument({ request: action.request() });
  const [file, setFile] = useState<File | null>(null);
  const [replacement, setReplacement] = useState<DocumentOut | null>(null);
  const busy = useRef(false);
  const files =
    query.data?.status === 200
      ? query.data.data.filter(
          (d) =>
            !d.cancelledAt &&
            (!taskId ||
              d.taskId === taskId ||
              (includeUnassignedStatements && !d.taskId && d.kind === 'BANK_STATEMENT_1C')),
        )
      : [];

  const send = async () => {
    if (!file || busy.current || disabled) return;
    const kind = replacement
      ? uploadKind(replacement.kind)
      : file.name.toLowerCase().endsWith('.txt')
        ? 'BANK_STATEMENT_1C'
        : 'OTHER';
    if (!kind) return;
    busy.current = true;
    try {
      const result = await upload.mutateAsync({
        data: {
          applicationId,
          ...(taskId ? { taskId } : {}),
          ...(replacement ? { replacesId: replacement.id } : {}),
          kind,
          file,
        },
      });
      if (result.status === 201) {
        action.reset();
        setFile(null);
        setReplacement(null);
        await client.invalidateQueries({ queryKey: getListDocumentsQueryKey({ applicationId }) });
        onUploaded?.(result.data);
      }
    } catch {
      // Retrying keeps the same file and idempotency key after a lost response.
    } finally {
      busy.current = false;
    }
  };
  return (
    <Stack gap="xs">
      {query.isPending ? <Loader size="sm" aria-label={dt.loading} /> : null}
      {query.error ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {files.map((document) => (
        <Stack key={document.id} gap={4}>
          <Group justify="space-between">
            <Anchor
              target="_blank"
              rel="noopener noreferrer"
              href={resolveUrl(getDownloadDocumentUrl(document.id, { preview: true }))}
            >
              {document.filename}
            </Anchor>
            <Button
              size="compact-xs"
              variant="subtle"
              disabled={disabled || upload.isPending || !uploadKind(document.kind)}
              aria-label={`${dt.replace}: ${document.filename}`}
              onClick={() => {
                setReplacement(document);
                setFile(null);
                action.reset();
                upload.reset();
              }}
            >
              {dt.replace}
            </Button>
          </Group>
          <ParseStatus document={document} />
          {document.parseStatus === 'PARSED' && document.kind === 'BANK_STATEMENT_1C' ? (
            <StatementConfirmation document={document} disabled={disabled} />
          ) : null}
        </Stack>
      ))}
      {replacement ? (
        <Group>
          <Text size="sm">{dt.replacing(replacement.filename)}</Text>
          <Button
            size="compact-xs"
            variant="subtle"
            disabled={upload.isPending}
            onClick={() => {
              setReplacement(null);
              setFile(null);
              action.reset();
              upload.reset();
            }}
          >
            {dt.cancelReplacement}
          </Button>
        </Group>
      ) : null}
      <FileInput
        label={dt.attach}
        description={dt.limits}
        accept={
          replacement ? (replacement.kind === 'BANK_STATEMENT_1C' ? '.txt' : '.pdf') : '.pdf,.txt'
        }
        value={file}
        disabled={disabled || upload.isPending}
        clearable
        onChange={(next) => {
          setFile(next);
          action.reset();
          upload.reset();
        }}
      />
      {upload.error ? <ProblemAlert error={upload.error} /> : null}
      <Button
        variant="default"
        disabled={!file || disabled}
        loading={upload.isPending}
        onClick={() => void send()}
      >
        {dt.upload}
      </Button>
    </Stack>
  );
}
