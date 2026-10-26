import { Box, Text } from '@mantine/core';
import { tokens } from '@/app/theme';
import { shell } from '@/texts';

/**
 * Постоянная плашка «Демо-прототип. Все данные синтетические» (D-085): есть на любом экране,
 * включая вход и ошибки, поэтому живёт в корневой раскладке. Тёмная, с красной меткой (D-113):
 * заметна, но не спорит с красными кнопками.
 */
export function DemoBanner() {
  const { demoBanner } = tokens;
  return (
    <Box
      component="aside"
      aria-labelledby="demo-banner-text"
      data-testid="demo-banner"
      title={shell.demoBannerHint}
      py={6}
      px="md"
      ta="center"
      style={{ background: demoBanner.background, color: demoBanner.color }}
    >
      <Box
        component="span"
        aria-hidden="true"
        mr={8}
        px={6}
        py={1}
        fz={11}
        fw={700}
        style={{
          background: demoBanner.badge,
          color: '#ffffff',
          borderRadius: 4,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {shell.demoBadge}
      </Box>
      <Text id="demo-banner-text" component="span" size="sm" fw={500} c="inherit">
        {shell.demoBanner}
      </Text>
    </Box>
  );
}
