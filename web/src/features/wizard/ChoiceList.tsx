import type { ReactNode } from 'react';
import { Badge, Button, Group, Stack, Text } from '@mantine/core';
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
    <Stack gap="sm" maw={640}>
      <Stack gap="sm" role="group" aria-label={wizard.choicesLabel}>
        {choices.map((choice) => {
          const isSelected = choice.value === selected;
          return (
            <Button
              key={choice.value}
              variant={isSelected ? 'light' : 'default'}
              size="md"
              fullWidth
              h="auto"
              py="md"
              px="lg"
              justify="flex-start"
              disabled={disabled}
              aria-pressed={isSelected}
              data-choice={choice.value}
              styles={{ label: { whiteSpace: 'normal', textAlign: 'left' } }}
              onClick={() => onSelect(choice.value)}
            >
              <Stack gap={2}>
                <Group gap="xs">
                  <Text fw={600}>{choice.title}</Text>
                  {choice.badge ? (
                    <Badge variant="light" color="green">
                      {choice.badge}
                    </Badge>
                  ) : null}
                </Group>
                {choice.description ? (
                  <Text size="sm" c="dimmed" fw={400}>
                    {choice.description}
                  </Text>
                ) : null}
              </Stack>
            </Button>
          );
        })}
      </Stack>
      {onUnknown ? (
        <div>
          <Button variant="subtle" px={0} disabled={disabled} onClick={onUnknown}>
            {unknownLabel}
          </Button>
        </div>
      ) : null}
      {children}
    </Stack>
  );
}
