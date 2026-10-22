import { Text } from '@mantine/core';
import { shell } from '@/texts';

/** Подсказка «Откройте на компьютере»: видна только при ширине окна меньше 1280 px (styles.css) */
export function DesktopHint() {
  return (
    <Text className="desktop-hint" role="note" size="sm" ta="center" py="xs" bg="gray.1">
      {shell.desktopHint}
    </Text>
  );
}
