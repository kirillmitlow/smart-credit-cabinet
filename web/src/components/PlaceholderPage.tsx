import { Stack, Text, Title } from '@mantine/core';
import { usePageHeading } from '@/lib/usePageHeading';
import { placeholders } from '@/texts';

export interface PlaceholderContent {
  title: string;
  body: string;
}

/** Страница-заглушка для экранов, которые делают следующие задачи (T-408…T-435) */
export function PlaceholderPage({ content }: { content: PlaceholderContent }) {
  const headingRef = usePageHeading(content.title);
  return (
    <Stack gap="sm" data-testid="placeholder-page">
      <Title order={1} ref={headingRef} tabIndex={-1}>
        {content.title}
      </Title>
      <Text>{content.body}</Text>
      <Text size="sm" c="dimmed">
        {placeholders.soon}
      </Text>
    </Stack>
  );
}
