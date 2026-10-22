import { Box, Text } from '@mantine/core';
import { useOnline } from '@/lib/useOnline';
import { shell } from '@/texts';

/** Тонкая полоса сверху «Нет связи»: пока сети нет, действия блокируются (60-01) */
export function OfflineBar() {
  const online = useOnline();
  if (online) return null;
  return (
    <Box role="alert" py={4} ta="center" bg="dark.7" c="white" data-testid="offline-bar">
      <Text size="sm" c="inherit">
        {shell.offlineBar}
      </Text>
    </Box>
  );
}
