import { documentTexts as dt } from '@/texts/documents';
import { useEffect, useRef, useState } from 'react';
import { Anchor, Button, FileInput, Group, Loader, Paper, Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getDownloadDocumentUrl,
  getListDocumentsQueryKey,
  getListApplicationTasksQueryKey,
  useListDocuments,
  useUploadDocument,
  useGenerateDemoStatement,
} from '@/api/generated/api';
import { UploadDocumentBodyKind, type DocumentOut } from '@/api/generated/model';
import { resolveUrl } from '@/api/client';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { StatementConfirmation } from './StatementConfirmation';
import { usePublicConfig } from '@/features/auth/session';

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
  allowDemoStatement = false,
}: {
  applicationId: string;
  taskId?: string;
  disabled?: boolean;
  onUploaded?: (file: DocumentOut) => void;
  includeUnassignedStatements?: boolean;
  allowDemoStatement?: boolean;
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
  const demoAction = useActionKey();
  const generation = useGenerateDemoStatement<unknown>({ request: demoAction.request() });
  const demoMode = usePublicConfig().data?.demoMode === true;
  const working = upload.isPending || generation.isPending;
  const [selectionError, setSelectionError] = useState<string | null>(null);
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

  const documentState =
    query.data?.status === 200
      ? query.data.data
          .map((d) => [d.id, d.parseStatus, d.confirmedAt, d.cancelledAt].join(':'))
          .join('|')
      : null;
  useEffect(() => {
    if (taskId && documentState !== null) {
      void client.invalidateQueries({ queryKey: getListApplicationTasksQueryKey(applicationId) });
    }
  }, [applicationId, taskId, documentState, client]);

  const choose = (next: File | null) => {
    if (disabled || working) return;
    let error: string | null = null;
    if (next) {
      const txt = next.name.toLowerCase().endsWith('.txt');
      const pdf = next.name.toLowerCase().endsWith('.pdf');
      const valid = replacement
        ? replacement.kind === 'BANK_STATEMENT_1C'
          ? txt
          : pdf
        : txt || pdf;
      if (!valid) error = dt.fileTypeError;
      else if (next.size === 0) error = dt.emptyFile;
      else if (next.size > (txt ? 5 : 10) * 1024 * 1024)
        error = txt ? dt.statementTooLarge : dt.pdfTooLarge;
    }
    setSelectionError(error);
    setFile(error ? null : next);
    action.reset();
    upload.reset();
    generation.reset();
  };

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
        setSelectionError(null);
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
  const generate = async () => {
    if (!taskId || busy.current || disabled) return;
    busy.current = true;
    try {
      const result = await generation.mutateAsync({
        data: { applicationId, taskId, ...(replacement ? { replacesId: replacement.id } : {}) },
      });
      if (result.status === 201) {
        demoAction.reset();
        setReplacement(null);
        setFile(null);
        setSelectionError(null);
        await client.invalidateQueries({ queryKey: getListDocumentsQueryKey({ applicationId }) });
        onUploaded?.(result.data);
      }
    } catch {
      // Preserve the key after a lost response: retry must return the saved original.
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
              disabled={disabled || working || !uploadKind(document.kind)}
              aria-label={`${dt.replace}: ${document.filename}`}
              onClick={() => {
                setSelectionError(null);
                setReplacement(document);
                setFile(null);
                action.reset();
                upload.reset();
                demoAction.reset();
                generation.reset();
              }}
            >
              {dt.replace}
            </Button>
          </Group>
          {document.origin === 'DEMO_GENERATED' ? <Text size="xs">{dt.demoGenerated}</Text> : null}
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
            disabled={working}
            onClick={() => {
              setSelectionError(null);
              setReplacement(null);
              setFile(null);
              action.reset();
              upload.reset();
              demoAction.reset();
              generation.reset();
            }}
          >
            {dt.cancelReplacement}
          </Button>
        </Group>
      ) : null}
      <Paper
        withBorder
        p="sm"
        role="group"
        aria-label={dt.dropArea}
        aria-disabled={disabled || working}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes('Files')) {
            event.preventDefault();
            event.dataTransfer.dropEffect = disabled || working ? 'none' : 'copy';
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (disabled || working || event.dataTransfer.files.length === 0) return;
          if (event.dataTransfer.files.length !== 1) {
            choose(null);
            setSelectionError(dt.singleFile);
            return;
          }
          choose(event.dataTransfer.files[0] ?? null);
        }}
      >
        <Text size="sm" mb="xs">
          {dt.dropHelp}
        </Text>
        <FileInput
          label={dt.attach}
          description={dt.limits}
          accept={
            replacement ? (replacement.kind === 'BANK_STATEMENT_1C' ? '.txt' : '.pdf') : '.pdf,.txt'
          }
          value={file}
          disabled={disabled || working}
          error={selectionError ? <span role="alert">{selectionError}</span> : undefined}
          clearable
          clearButtonProps={{ 'aria-label': dt.clearFile }}
          onChange={choose}
        />
      </Paper>
      {upload.error ? <ProblemAlert error={upload.error} /> : null}
      <Button
        variant="default"
        disabled={!file || disabled || generation.isPending}
        loading={upload.isPending}
        onClick={() => void send()}
      >
        {dt.upload}
      </Button>
      {demoMode &&
      allowDemoStatement &&
      taskId &&
      (!replacement || replacement.kind === 'BANK_STATEMENT_1C') ? (
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            {dt.demoStatementHelp}
          </Text>
          {generation.error ? <ProblemAlert error={generation.error} /> : null}
          <Button
            variant="light"
            loading={generation.isPending}
            disabled={disabled || upload.isPending}
            onClick={() => void generate()}
          >
            {dt.generateStatement}
          </Button>
        </Stack>
      ) : null}
    </Stack>
  );
}
