import { Alert, Button, Group, Stack, Text } from '@mantine/core';
import { errorView, fill, supportCodeLabel } from '@/texts';

export interface ProblemAlertProps {
  /** Что пришло от запроса: AppError, обычная ошибка или что угодно */
  error: unknown;
  /** Нажатие на кнопку действия из словаря («Повторить», «Обновить»…) */
  onAction?: () => void;
}

/**
 * Единый показ ошибки сервера в блоке страницы: текст берётся из словаря по `code`,
 * `detail` не показываем; неизвестный код даёт общий текст, номер запроса — мелкой строкой.
 */
export function ProblemAlert({ error, onAction }: ProblemAlertProps) {
  const view = errorView(error);
  return (
    <Alert color="red" variant="light" role="alert" data-error-code={view.code}>
      <Stack gap="xs">
        <Text>{view.text}</Text>
        {view.action && onAction ? (
          <Group>
            <Button size="compact-sm" variant="light" onClick={onAction}>
              {view.action}
            </Button>
          </Group>
        ) : null}
        {view.requestId ? (
          <Text size="xs" c="dimmed">
            {fill(supportCodeLabel, { requestId: view.requestId })}
          </Text>
        ) : null}
      </Stack>
    </Alert>
  );
}
