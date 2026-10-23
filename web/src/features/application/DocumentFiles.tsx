import { useRef, useState } from 'react';
import { Anchor, Button, FileInput, Group, Loader, Stack, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getDownloadDocumentUrl,
  getListDocumentsQueryKey,
  useListDocuments,
  useUploadDocument,
} from '@/api/generated/api';
import type { DocumentOut } from '@/api/generated/model';
import { resolveUrl } from '@/api/client';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';

export function DocumentFiles({
  applicationId,
  taskId,
  disabled = false,
  onUploaded,
}: {
  applicationId: string;
  taskId?: string;
  disabled?: boolean;
  onUploaded?: (file: DocumentOut) => void;
}) {
  const client = useQueryClient();
  const query = useListDocuments({ applicationId });
  const action = useActionKey();
  const upload = useUploadDocument({ request: action.request() });
  const [file, setFile] = useState<File | null>(null);
  const busy = useRef(false);
  const files =
    query.data?.status === 200
      ? query.data.data.filter((d) => !d.cancelledAt && (!taskId || d.taskId === taskId))
      : [];

  const send = async () => {
    if (!file || busy.current || disabled) return;
    busy.current = true;
    try {
      const result = await upload.mutateAsync({
        data: {
          applicationId,
          ...(taskId ? { taskId } : {}),
          kind: file.name.toLowerCase().endsWith('.txt') ? 'BANK_STATEMENT_1C' : 'OTHER',
          file,
        },
      });
      if (result.status === 201) {
        action.reset();
        setFile(null);
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
      {query.isPending ? <Loader size="sm" aria-label="Получаем список документов" /> : null}
      {query.error ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {files.map((document) => (
        <Group key={document.id} justify="space-between">
          <Anchor
            target="_blank"
            rel="noopener noreferrer"
            href={resolveUrl(getDownloadDocumentUrl(document.id, { preview: true }))}
          >
            {document.filename}
          </Anchor>
          <Text size="xs" c="dimmed">
            {document.parseStatus === 'PENDING'
              ? 'Файл сохранён; сведения ещё не разобраны'
              : 'Файл сохранён'}
          </Text>
        </Group>
      ))}
      <FileInput
        label="Прикрепить документ"
        description="PDF до 10 МБ или выписка 1С в TXT до 5 МБ"
        accept=".pdf,.txt"
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
        Загрузить файл
      </Button>
    </Stack>
  );
}
