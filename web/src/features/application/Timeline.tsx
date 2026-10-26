import { Box, Loader, SimpleGrid, Stack, Text, VisuallyHidden } from '@mantine/core';
import { graphitePalette, tokens } from '@/app/theme';
import { applicationPage, timelineProgress } from '@/texts';
import type { StepState, TimelineModel, TimelineStep } from './timelineModel';

/** Цвет полосы шага на тёмном фоне: пройден — белый, текущий — светло-красный, впереди — графит */
const barColor: Record<StepState, string> = {
  done: '#ffffff',
  running: tokens.accentOnDark,
  waiting: graphitePalette[7],
};

function StepItem({ step, checks }: { step: TimelineStep; checks: TimelineModel['checks'] }) {
  const running = step.state === 'running';
  const waiting = step.state === 'waiting';
  const muted = tokens.header.muted;
  return (
    <Box
      component="li"
      aria-current={running ? 'step' : undefined}
      data-step={step.key}
      data-state={step.state}
    >
      <Stack gap={8}>
        <Box
          h={6}
          style={{ borderRadius: 3, background: barColor[step.state] }}
          aria-hidden="true"
        />
        <Text
          fw={running ? 700 : 600}
          fz={15}
          style={{ color: running ? tokens.accentOnDark : waiting ? muted : '#ffffff' }}
        >
          {running ? (
            <Loader size={12} color={tokens.accentOnDark} mr={6} aria-hidden="true" />
          ) : null}
          {step.title}
          <VisuallyHidden> ({applicationPage.stepState[step.state]})</VisuallyHidden>
        </Text>
        {step.text ? (
          <Text size="sm" style={{ color: running ? '#ffffff' : muted }}>
            {step.text}
          </Text>
        ) : null}
        {step.key === 'checking' && (running || (checks && !waiting)) ? (
          <Box>
            <Text size="sm" fw={500} style={{ color: muted }}>
              {applicationPage.checksHeading}
            </Text>
            <Stack component="ul" gap={2} m={0} p={0} style={{ listStyle: 'none' }}>
              {checks
                ? checks.map((check) => (
                    <Text
                      component="li"
                      size="sm"
                      key={check.key}
                      data-check={check.key}
                      data-state={check.state}
                      style={{ color: check.state === 'done' ? '#e4e4e7' : muted }}
                    >
                      <span aria-hidden="true">
                        {check.state === 'done' ? '✓ ' : check.state === 'delayed' ? '! ' : ''}
                      </span>
                      {check.title}
                      {check.state === 'done' ? (
                        <VisuallyHidden>: {timelineProgress.checkState.done}</VisuallyHidden>
                      ) : (
                        `: ${timelineProgress.checkState[check.state]}`
                      )}
                    </Text>
                  ))
                : applicationPage.checks.map((check) => (
                    <Text component="li" size="sm" key={check} style={{ color: muted }}>
                      {check}
                    </Text>
                  ))}
            </Stack>
          </Box>
        ) : null}
      </Stack>
    </Box>
  );
}

/**
 * Горизонтальный таймлайн в тёмной полосе страницы заявки (60-03 №8, D-113): шесть шагов в ряд,
 * у каждого полоса-индикатор. Текущий шаг помечен `aria-current`. Состояния проверок — из журнала,
 * до загрузки — перечень без галочек.
 */
export function Timeline({ model }: { model: TimelineModel }) {
  if (model.steps.length === 0) return null;
  return (
    <SimpleGrid
      component="ol"
      cols={model.steps.length}
      spacing="md"
      p={0}
      m={0}
      style={{ listStyle: 'none' }}
      aria-label={applicationPage.timelineLabel}
      data-testid="timeline"
    >
      {model.steps.map((step) => (
        <StepItem key={step.key} step={step} checks={model.checks} />
      ))}
    </SimpleGrid>
  );
}
