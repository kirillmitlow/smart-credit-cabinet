import { Box, Text } from '@mantine/core';
import { tokens } from '@/app/theme';
import { shell } from '@/texts';

/**
 * Постоянная плашка «Демо-прототип. Все данные синтетические» (D-085): есть на любом экране,
 * включая вход и ошибки, поэтому живёт в корневой раскладке.
 */
export function DemoBanner() {
  return (
    <Box
      component="aside"
      aria-labelledby="demo-banner-text"
      data-testid="demo-banner"
      title={shell.demoBannerHint}
      py={6}
      px="md"
      ta="center"
      style={{ background: tokens.demoBanner.background, color: tokens.demoBanner.color }}
    >
      <Text id="demo-banner-text" size="sm" fw={500} c="inherit">
        {shell.demoBanner}
      </Text>
    </Box>
  );
}
