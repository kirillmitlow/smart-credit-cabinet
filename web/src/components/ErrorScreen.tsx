import { useEffect, useRef, type ReactNode } from 'react';
import { Button, CopyButton, Group, Stack, Text, Title } from '@mantine/core';
import { copySupportCode, fill, shell, supportCodeCopied, supportCodeLabel } from '@/texts';

export interface ErrorScreenProps {
  title: string;
  body?: string;
  /** Номер запроса для строки «Код для поддержки» */
  requestId?: string | null;
  /** «Повторить» */
  onRetry?: () => void;
  retryLabel?: string;
  /** Дополнительные кнопки (ссылки «Вернуться», «На главную») */
  actions?: ReactNode;
}

/**
 * Общий экран ошибки на всю страницу: фраза по-человечески, кнопка «Повторить», мелко «Код для поддержки»
 * с копированием (60-01). Заголовок получает фокус, чтобы скринридер сразу прочитал, что случилось.
 */
export function ErrorScreen({
  title,
  body,
  requestId,
  onRetry,
  retryLabel,
  actions,
}: ErrorScreenProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <Stack align="center" gap="md" py="xl" role="alert" data-testid="error-screen">
      <Title order={1} size="h2" ref={headingRef} tabIndex={-1}>
        {title}
      </Title>
      {body ? <Text ta="center">{body}</Text> : null}
      <Group>
        {onRetry ? <Button onClick={onRetry}>{retryLabel ?? shell.common.retry}</Button> : null}
        {actions}
      </Group>
      {requestId ? (
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {fill(supportCodeLabel, { requestId })}
          </Text>
          <CopyButton value={requestId}>
            {({ copied, copy }) => (
              <Button variant="subtle" size="compact-xs" onClick={copy}>
                {copied ? supportCodeCopied : copySupportCode}
              </Button>
            )}
          </CopyButton>
        </Group>
      ) : null}
    </Stack>
  );
}
