import type { ReactNode } from 'react';
import { Badge, Button, Group, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { fonts, tokens } from '@/app/theme';
import { wizard } from '@/texts';

export interface Choice {
  value: string;
  title: string;
  /** Пример или пояснение мелким шрифтом под названием */
  description?: string;
  /** Пометка рядом с названием (например, «По силам вашей компании») */
  badge?: string;
}

/**
 * Один вопрос крупными карточками (10-07, принцип 1). Это кнопки: достаются клавишей Tab,
 * нажимаются Enter/пробелом; выбранный ответ помечен `aria-pressed`. Нажатие сразу ведёт дальше.
 */
export function ChoiceList({
  choices,
  selected,
  disabled,
  onSelect,
  unknownLabel = wizard.unknown,
  onUnknown,
  children,
}: {
  choices: readonly Choice[];
  selected?: string | null;
  disabled?: boolean;
  onSelect: (value: string) => void;
  /** Подпись кнопки «Не знаю»; без `onUnknown` кнопки нет */
  unknownLabel?: string;
  onUnknown?: () => void;
  children?: ReactNode;
}) {
  return (
    <Stack gap="md" maw={960}>
      <SimpleGrid
        cols={{ base: 1, sm: 2 }}
        spacing="md"
        role="group"
        aria-label={wizard.choicesLabel}
      >
        {choices.map((choice) => {
          const isSelected = choice.value === selected;
          return (
            <UnstyledButton
              key={choice.value}
              disabled={disabled}
              aria-pressed={isSelected}
              data-choice={choice.value}
              className="scc-choice"
              onClick={() => onSelect(choice.value)}
            >
              <Stack gap={6}>
                <Group gap="xs" wrap="wrap">
                  <Text ff={fonts.display} fw={700} fz={16} lh={1.3}>
                    {choice.title}
                  </Text>
                  {choice.badge ? (
                    <Badge radius="xl" tt="none" styles={{ root: tokens.status.success }}>
                      {choice.badge}
                    </Badge>
                  ) : null}
                </Group>
                {choice.description ? (
                  <Text size="sm" c="dimmed">
                    {choice.description}
                  </Text>
                ) : null}
              </Stack>
            </UnstyledButton>
          );
        })}
      </SimpleGrid>
      {onUnknown ? (
        <div>
          <Button variant="outline" color="dark" disabled={disabled} onClick={onUnknown}>
            {unknownLabel}
          </Button>
        </div>
      ) : null}
      {children}
    </Stack>
  );
}
