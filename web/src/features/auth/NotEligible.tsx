import { Button, List, Stack, Text, Title } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { login } from '@/texts';
import { useFocusOnMount } from './useFocusOnMount';

const t = login.notEligible;

/**
 * Шаг 2в (60-03 №1): самозанятый (`NOT_ELIGIBLE`). Не тупик: объяснение и «Как стать ИП» текстом
 * прямо на странице, без ухода из продукта. До кода не доходим.
 */
export function NotEligible({ onBack }: { onBack: () => void }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [opened, { toggle }] = useDisclosure(false);
  return (
    <Stack gap="md" data-testid="not-eligible">
      <Title order={2} size="h3" ref={headingRef} tabIndex={-1}>
        {t.heading}
      </Title>
      <Text>{t.body}</Text>
      <Button
        variant="light"
        onClick={toggle}
        aria-expanded={opened}
        aria-controls="how-to-ip"
        style={{ alignSelf: 'flex-start' }}
      >
        {t.howTo}
      </Button>
      <div id="how-to-ip" hidden={!opened}>
        <Stack gap="xs">
          <Title order={3} size="h4">
            {t.howToTitle}
          </Title>
          <List type="ordered">
            {t.steps.map((step) => (
              <List.Item key={step}>{step}</List.Item>
            ))}
          </List>
        </Stack>
      </div>
      <Button variant="default" onClick={onBack} style={{ alignSelf: 'flex-start' }}>
        {t.back}
      </Button>
    </Stack>
  );
}
