import { Box, Group, Loader, Stack, Text, ThemeIcon, VisuallyHidden } from '@mantine/core';
import { applicationPage } from '@/texts';
import type { StepState, TimelineModel, TimelineStep } from './timelineModel';

function Marker({ state, index }: { state: StepState; index: number }) {
  if (state === 'running') {
    return (
      <ThemeIcon variant="light" radius="xl" size={28} aria-hidden="true">
        <Loader size={14} />
      </ThemeIcon>
    );
  }
  if (state === 'done') {
    return (
      <ThemeIcon radius="xl" size={28} aria-hidden="true">
        ✓
      </ThemeIcon>
    );
  }
  return (
    <ThemeIcon variant="default" radius="xl" size={28} aria-hidden="true">
      {index + 1}
    </ThemeIcon>
  );
}

function StepItem({ step, index }: { step: TimelineStep; index: number }) {
  const running = step.state === 'running';
  return (
    <li aria-current={running ? 'step' : undefined} data-step={step.key} data-state={step.state}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Marker state={step.state} index={index} />
        <Box>
          <Text fw={running ? 700 : 600} c={step.state === 'waiting' ? 'dimmed' : undefined}>
            {step.title}
            <VisuallyHidden> ({applicationPage.stepState[step.state]})</VisuallyHidden>
          </Text>
          {step.text ? (
            <Text size="sm" c="dimmed">
              {step.text}
            </Text>
          ) : null}
          {running && step.key === 'checking' ? (
            <Box mt={4}>
              <Text size="sm" fw={500}>
                {applicationPage.checksHeading}
              </Text>
              <Stack component="ul" gap={2} m={0} pl="md">
                {applicationPage.checks.map((check) => (
                  <Text component="li" size="sm" c="dimmed" key={check}>
                    {check}
                  </Text>
                ))}
              </Stack>
            </Box>
          ) : null}
        </Box>
      </Group>
    </li>
  );
}

/**
 * Вертикальный таймлайн (60-03 №8). Список с номерами шагов; текущий шаг помечен `aria-current`.
 * Подшаги проверки (реестр, налоговая, кредитная история) пока показаны перечнем без галочек:
 * галочки придут с ручкой `GET …/timeline` (T-255).
 */
export function Timeline({ model }: { model: TimelineModel }) {
  if (model.steps.length === 0) return null;
  return (
    <Stack
      component="ol"
      gap="lg"
      p={0}
      m={0}
      style={{ listStyle: 'none' }}
      aria-label={applicationPage.timelineLabel}
      data-testid="timeline"
    >
      {model.steps.map((step, index) => (
        <StepItem key={step.key} step={step} index={index} />
      ))}
    </Stack>
  );
}
