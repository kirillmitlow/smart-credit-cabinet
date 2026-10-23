import { Badge, Stack, Text } from '@mantine/core';
import type { BankRecommendation } from '@/api/generated/model';
import { bankWorkspace as t } from '@/texts/bank';

const colors: Record<string, string> = {
  APPROVED: 'green',
  COUNTER_OFFER: 'orange',
  NEEDS_INFO: 'blue',
  REJECTED: 'red',
};

export function BankRecommendationView({ value }: { value: BankRecommendation | null }) {
  if (!value)
    return (
      <Text size="sm" c="dimmed">
        {t.noRecommendation}
      </Text>
    );
  const title = Object.prototype.hasOwnProperty.call(t.outcomes, value.outcome)
    ? t.outcomes[value.outcome as keyof typeof t.outcomes]
    : value.outcome;
  const hint = Object.prototype.hasOwnProperty.call(t.hints, value.hint)
    ? t.hints[value.hint as keyof typeof t.hints]
    : null;
  return (
    <Stack gap={4}>
      <Badge
        variant="light"
        color={colors[value.outcome] ?? 'gray'}
        c="dark.9"
        style={{ height: 'auto', whiteSpace: 'normal' }}
      >
        {title}
      </Badge>
      {hint ? <Text size="sm">{hint}</Text> : null}
    </Stack>
  );
}
