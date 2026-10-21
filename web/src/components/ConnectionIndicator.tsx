import { Text } from '@mantine/core';
import { useConnectionStatus } from '@/lib/events/connection-context';
import { shell } from '@/texts';

const labels = {
  connecting: '',
  connected: shell.connection.connected,
  reconnecting: shell.connection.reconnecting,
  polling: shell.connection.polling,
} as const;

/**
 * Три состояния связи мелкой подписью в шапке (60-01, 50-11). Область `status` существует всегда,
 * поэтому смена состояния озвучивается скринридером вежливо, без перебивания.
 */
export function ConnectionIndicator() {
  const status = useConnectionStatus();
  return (
    <Text
      role="status"
      aria-live="polite"
      aria-label={shell.connection.label}
      size="xs"
      c="dimmed"
      data-status={status}
      data-testid="connection-indicator"
    >
      {labels[status]}
    </Text>
  );
}
