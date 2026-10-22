import { Box, Text } from '@mantine/core';
import { shell } from '@/texts';

/** Подвал с пометкой «данные придуманы» (D-085): вторая подпись к плашке в шапке */
export function AppFooter() {
  return (
    <Box component="footer" py="md" px="md" ta="center" data-testid="app-footer">
      <Text size="xs" c="dimmed">
        {shell.footer}
      </Text>
    </Box>
  );
}
