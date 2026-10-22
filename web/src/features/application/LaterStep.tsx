import { Alert, Badge, Group, Stack, Text, Title } from '@mantine/core';
import { applicationForm } from '@/texts';

/**
 * Заглушка шага, который делает отдельная задача (данные компании — T-417, что нужно для продукта —
 * T-418). Выглядит как честная метка «появится позже», а не как рабочий шаг.
 */
export function LaterStep({ title, body }: { title: string; body: string }) {
  return (
    <Stack gap="md" maw={520} data-testid="later-step">
      <Group gap="sm">
        <Title order={2} size="h3">
          {title}
        </Title>
        <Badge variant="light" color="gray">
          {applicationForm.later.badge}
        </Badge>
      </Group>
      <Alert color="gray" variant="light">
        <Text>{body}</Text>
      </Alert>
    </Stack>
  );
}
