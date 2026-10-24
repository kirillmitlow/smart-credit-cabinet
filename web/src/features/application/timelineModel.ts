/**
 * Модель таймлайна: из статуса заявки (14 внутренних) строим шесть клиентских шагов и паузу
 * «Нужна ваша помощь» (20-02, «Что видит клиент»; 60-06). Это не копия стейт-машины, а только
 * отображение статуса в слова. Шаги выводятся из статуса целиком, поэтому повтор события
 * («то же самое пришло дважды») ничего не дублирует.
 */
import { formatDateTime, formatMoney } from '@/lib/format';
import type { ApplicationTimelineOut } from '@/api/generated/model';
import {
  applicationPage,
  fillKnown,
  needsHelpStep,
  timelineNotes,
  timelineProgress,
  timelineSteps,
} from '@/texts';
import type { ClientStepKey } from './statuses';

export type StepState = 'done' | 'running' | 'waiting';

export interface TimelineStep {
  key: ClientStepKey;
  state: StepState;
  title: string;
  /** Пояснение для текущего состояния шага; у ждущих шагов его нет */
  text: string | null;
}

export interface TimelineModel {
  steps: TimelineStep[];
  checks?: {
    key: string;
    title: string;
    state: 'waiting' | 'running' | 'done' | 'delayed';
  }[];
  /** Шаг, который «идёт сейчас» (или последний готовый): его читает скринридер */
  current: TimelineStep | null;
  /** Заявка закрыта без решения: пояснение вместо шагов */
  note: string | null;
}

/** Сервер задаёт положение шагов; клиент только переводит разрешённые ключи в текст. */
export function timelineFromEvents(data: ApplicationTimelineOut): TimelineModel {
  const texts: Record<string, string> = {};
  for (const step of timelineSteps) {
    texts[`${step.key}.running`] = step.running;
    texts[`${step.key}.done`] = step.done;
  }
  texts['needsHelp.running'] = applicationPage.needsHelpGeneric;
  texts['decision.approved'] = applicationPage.decisionDone.approved;
  texts['decision.counter'] = applicationPage.decisionDone.counter;
  texts['decision.rejected'] = applicationPage.decisionDone.rejected;
  texts['money.done'] = timelineProgress.moneyDone;
  texts['checking.delayed'] = timelineProgress.checksDelayed;
  const steps = data.steps.map((step): TimelineStep => {
    const template = texts[step.textKey];
    return {
      key: step.key,
      state: step.state,
      title:
        step.key === 'needsHelp'
          ? needsHelpStep.title
          : (timelineSteps.find((s) => s.key === step.key)?.title ?? ''),
      text:
        step.state === 'waiting' || !template
          ? null
          : fillKnown(template, {
              date: typeof step.params?.date === 'string' ? formatDateTime(step.params.date) : null,
            }),
    };
  });
  return {
    steps,
    checks: data.checks.map((check) => ({
      key: check.key,
      title: timelineProgress.checks[check.key],
      state: check.state,
    })),
    current:
      steps.find((step) => step.state === 'running') ??
      [...steps].reverse().find((step) => step.state === 'done') ??
      null,
    note: data.noteKey ? timelineNotes[data.noteKey] : null,
  };
}

export interface TimelineInput {
  status: string;
  submittedAt: string | null;
  amountRub: number | null;
}

interface Position {
  active: ClientStepKey;
  /** Состояние активного шага; всё левее него готово, всё правее ждёт */
  activeState: 'running' | 'done';
  /** После отказа дальше идти некуда: ждущие шаги не показываем */
  hideWaiting?: boolean;
}

function positionOf(status: string): Position | null {
  switch (status) {
    case 'SUBMITTED':
      return { active: 'submitted', activeState: 'running' };
    case 'CHECKING':
      return { active: 'checking', activeState: 'running' };
    case 'NEEDS_INFO':
      return { active: 'needsHelp', activeState: 'running' };
    case 'MANUAL_REVIEW':
      return { active: 'evaluating', activeState: 'running' };
    case 'APPROVED':
    case 'COUNTER_OFFER':
      return { active: 'decision', activeState: 'done' };
    case 'REJECTED':
      return { active: 'decision', activeState: 'done', hideWaiting: true };
    case 'OFFER_ACCEPTED':
      return { active: 'signing', activeState: 'running' };
    case 'SIGNED':
    case 'DISBURSING':
      return { active: 'money', activeState: 'running' };
    case 'DISBURSED':
      return { active: 'money', activeState: 'done' };
    default:
      return null;
  }
}

const BASE_ORDER: readonly ClientStepKey[] = [
  'submitted',
  'checking',
  'evaluating',
  'decision',
  'signing',
  'money',
];

function decisionOutcome(status: string): string {
  if (status === 'COUNTER_OFFER') return applicationPage.decisionDone.counter;
  if (status === 'REJECTED') return applicationPage.decisionDone.rejected;
  return applicationPage.decisionDone.approved;
}

function stepText(key: ClientStepKey, state: StepState, input: TimelineInput): string | null {
  if (state === 'waiting') return null;
  if (key === 'needsHelp') return applicationPage.needsHelpGeneric;
  const base = timelineSteps.find((item) => item.key === key);
  if (!base) return null;
  if (state === 'running') return base.running;
  if (key === 'decision') return decisionOutcome(input.status);
  if (key === 'money') {
    return fillKnown(applicationPage.moneyDone, { amount: formatMoney(input.amountRub) });
  }
  const date = input.submittedAt && key === 'submitted' ? formatDateTime(input.submittedAt) : null;
  return fillKnown(base.done, { date });
}

export function buildTimeline(input: TimelineInput): TimelineModel {
  if (input.status === 'WITHDRAWN') {
    return { steps: [], current: null, note: timelineNotes.withdrawn };
  }
  if (input.status === 'EXPIRED') {
    return { steps: [], current: null, note: timelineNotes.expired };
  }
  const position = positionOf(input.status);
  if (!position) return { steps: [], current: null, note: null };

  const keys: ClientStepKey[] = [...BASE_ORDER];
  // пауза «Нужна ваша помощь» стоит между «Проверяем данные» и «Оцениваем» и видна, только пока нужна
  if (position.active === 'needsHelp') keys.splice(2, 0, 'needsHelp');
  const activeIndex = keys.indexOf(position.active);
  const shown = position.hideWaiting ? keys.slice(0, activeIndex + 1) : keys;

  const steps = shown.map((key, index): TimelineStep => {
    const state: StepState =
      index < activeIndex ? 'done' : index === activeIndex ? position.activeState : 'waiting';
    const title =
      key === 'needsHelp'
        ? needsHelpStep.title
        : (timelineSteps.find((item) => item.key === key)?.title ?? '');
    return { key, state, title, text: stepText(key, state, input) };
  });

  const current =
    steps.find((step) => step.state === 'running') ??
    [...steps].reverse().find((step) => step.state === 'done') ??
    null;
  return { steps, current, note: null };
}
