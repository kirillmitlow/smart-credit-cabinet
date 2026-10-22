import { useRef, useState } from 'react';
import { Button, Group, Loader, Progress, Stack, Text, Title } from '@mantine/core';
import { useLocation, useNavigate } from 'react-router';
import { useRecommendProduct } from '@/api/generated/api';
import type {
  WizardAnswersCollateral,
  WizardAnswersFrequency,
  WizardAnswersGovContract,
  WizardAnswersPaybackHorizon,
  WizardAnswersPurpose,
  WizardResult,
} from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { TermHint } from '@/components/TermHint';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { fill, termHints, wizard } from '@/texts';
import { AmountStep } from './AmountStep';
import { ChoiceList, type Choice } from './ChoiceList';
import {
  UNKNOWN,
  isWizardLocationState,
  paymentOptionsOf,
  previewAnswers,
  relevantAnswers,
  stepsFor,
  totalSteps,
  type Answers,
  type ResultLocationState,
  type StepId,
} from './wizardModel';

interface OptionText {
  readonly title: string;
  readonly example?: string;
}

function toChoices(options: Readonly<Record<string, OptionText>>): Choice[] {
  return Object.entries(options).map(([value, text]) => ({
    value,
    title: text.title,
    ...(text.example ? { description: text.example } : {}),
  }));
}

/** Ответы, от которых зависят следующие вопросы и расчёт: после их смены срок и расчёт устаревают */
const EARLY_KEYS = ['purpose', 'frequency', 'paybackHorizon', 'govContract', 'amountRub'] as const;

function changesEarlyAnswers(before: Answers, patch: Answers): boolean {
  return EARLY_KEYS.some((key) => key in patch && patch[key] !== before[key]);
}

/**
 * Мастер подбора (60-03 №4, 10-07): один вопрос на экран, «Не знаю» везде, «Назад» с пересчётом.
 * Слова «аннуитетный», «обеспечение» не используем (60-06). Продукт выбирает бэкенд, фронт только
 * задаёт вопросы и отправляет ответы в `POST /wizard/recommendations`.
 */
export function WizardPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const restored = isWizardLocationState(location.state) ? location.state : null;

  const [answers, setAnswers] = useState<Answers>(restored?.answers ?? {});
  const [applicationId, setApplicationId] = useState<string | null>(
    restored?.applicationId ?? null,
  );
  const [preview, setPreview] = useState<WizardResult | null>(null);
  const [step, setStep] = useState<StepId>('purpose');
  const recommend = useRecommendProduct();
  const retryRef = useRef<(() => void) | null>(null);
  const busyRef = useRef(false);

  const steps = stepsFor(answers, preview);
  const index = Math.max(0, steps.indexOf(step));
  const total = totalSteps(answers, preview);
  const pending = recommend.isPending;

  const question = questionTitle(step, answers);
  const headingRef = usePageHeading(question);

  /** Запрос к бэкенду; id черновика запоминаем, чтобы повторные запросы не создавали новые заявки */
  const ask = async (payload: Answers): Promise<WizardResult | null> => {
    if (busyRef.current) return null;
    busyRef.current = true;
    try {
      const response = await recommend.mutateAsync({
        data: { answers: payload, applicationId },
      });
      if (response.status !== 200) return null;
      if (response.data.applicationId) setApplicationId(response.data.applicationId);
      return response.data;
    } catch {
      return null; // текст ошибки показывает `recommend.error`
    } finally {
      busyRef.current = false;
    }
  };

  const showResult = (final: Answers, result: WizardResult) => {
    const state: ResultLocationState = {
      answers: final,
      applicationId: result.applicationId ?? applicationId,
      result,
    };
    void navigate('/wizard/result', { state });
  };

  /** Последний вопрос позади: отправляем все ответы и показываем результат */
  const finish = (current: Answers, currentPreview: WizardResult | null) => {
    const path = stepsFor(current, currentPreview);
    const final = relevantAnswers(current, path);
    const needsFinalCall = path.includes('payment') || path.includes('collateral');
    const run = async () => {
      if (!needsFinalCall && currentPreview) {
        showResult(final, currentPreview);
        return;
      }
      const result = await ask(final);
      if (result) showResult(final, result);
    };
    retryRef.current = () => void run();
    void run();
  };

  const goForward = (from: StepId, current: Answers, currentPreview: WizardResult | null) => {
    const path = stepsFor(current, currentPreview);
    const next = path[path.indexOf(from) + 1];
    if (next) setStep(next);
    else finish(current, currentPreview);
  };

  /** Ответ на карточку: запоминаем, при смене ранних ответов забываем расчёт и срок, идём дальше */
  const answer = (patch: Answers) => {
    const stale = changesEarlyAnswers(answers, patch);
    const next: Answers = { ...answers, ...patch };
    if (stale) delete next.termMonths;
    const nextPreview = stale ? null : preview;
    setAnswers(next);
    setPreview(nextPreview);
    goForward(step, next, nextPreview);
  };

  /** После суммы бэкенд сам скажет, нужны ли вопросы про платёж и залог */
  const submitAmount = (amountRub: number | null) => {
    const stale = changesEarlyAnswers(answers, { amountRub });
    const next: Answers = { ...answers, amountRub };
    if (stale) delete next.termMonths;
    setAnswers(next);
    const run = async () => {
      const result = await ask(previewAnswers(next));
      if (!result) return;
      setPreview(result);
      if (result.outcome !== 'RECOMMENDED') {
        showResult(relevantAnswers(next, stepsFor(next, null)), result);
        return;
      }
      goForward('amount', next, result);
    };
    retryRef.current = () => void run();
    void run();
  };

  const goBack = () => {
    const previous = steps[index - 1];
    if (previous) setStep(previous);
  };

  const paymentChoices: Choice[] = paymentOptionsOf(preview).map((option) => ({
    value: String(option.termMonths),
    title: formatTermMonths(option.termMonths),
    description: fill(wizard.payment.option, {
      payment: formatMoney(option.paymentRub),
      overpayment: formatMoney(option.overpaymentRub),
    }),
    ...(option.recommended ? { badge: wizard.payment.fits } : {}),
  }));

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          {wizard.title}
        </Text>
        <Text size="sm" fw={600} aria-live="polite">
          {fill(wizard.progress, { current: index + 1, total })}
        </Text>
        <Progress
          value={((index + 1) / total) * 100}
          size="sm"
          maw={640}
          aria-hidden="true"
          data-testid="wizard-progress"
        />
      </Stack>

      <Stack gap={4}>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {question}
        </Title>
        {restored && index === 0 ? <Text c="dimmed">{wizard.restored}</Text> : null}
        <StepHint step={step} />
      </Stack>

      {step === 'purpose' ? (
        <ChoiceList
          choices={toChoices(wizard.purpose.options)}
          selected={answers.purpose}
          disabled={pending}
          onSelect={(value) => answer({ purpose: value as WizardAnswersPurpose })}
          onUnknown={() => answer({ purpose: UNKNOWN })}
        />
      ) : null}

      {step === 'frequency' ? (
        <ChoiceList
          choices={toChoices(wizard.frequency.options)}
          selected={answers.frequency}
          disabled={pending}
          onSelect={(value) => answer({ frequency: value as WizardAnswersFrequency })}
          onUnknown={() => answer({ frequency: UNKNOWN })}
        />
      ) : null}

      {step === 'payback' ? (
        <ChoiceList
          choices={toChoices(wizard.payback.options)}
          selected={answers.paybackHorizon}
          disabled={pending}
          onSelect={(value) => answer({ paybackHorizon: value as WizardAnswersPaybackHorizon })}
          onUnknown={() => answer({ paybackHorizon: UNKNOWN })}
        />
      ) : null}

      {step === 'govContract' ? (
        <ChoiceList
          choices={toChoices(wizard.govContract.options)}
          selected={answers.govContract}
          disabled={pending}
          onSelect={(value) => answer({ govContract: value as WizardAnswersGovContract })}
          onUnknown={() => answer({ govContract: UNKNOWN })}
        />
      ) : null}

      {step === 'amount' ? (
        <AmountStep initial={answers.amountRub} disabled={pending} onSubmit={submitAmount} />
      ) : null}

      {step === 'payment' ? (
        <ChoiceList
          choices={paymentChoices}
          selected={answers.termMonths == null ? null : String(answers.termMonths)}
          disabled={pending}
          onSelect={(value) => answer({ termMonths: Number(value) })}
          unknownLabel={wizard.payment.unknown}
          onUnknown={() => answer({ termMonths: null })}
        />
      ) : null}

      {step === 'collateral' ? (
        <ChoiceList
          choices={toChoices(wizard.collateral.options)}
          selected={answers.collateral}
          disabled={pending}
          onSelect={(value) => answer({ collateral: value as WizardAnswersCollateral })}
        />
      ) : null}

      {pending ? (
        <Group gap="xs" role="status">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            {wizard.loading}
          </Text>
        </Group>
      ) : null}

      {recommend.isError ? (
        <Stack maw={640}>
          <ProblemAlert
            error={recommend.error}
            onAction={() => {
              recommend.reset();
              retryRef.current?.();
            }}
          />
        </Stack>
      ) : null}

      {index > 0 ? (
        <div>
          <Button variant="default" disabled={pending} onClick={goBack}>
            {wizard.back}
          </Button>
        </div>
      ) : null}
    </Stack>
  );
}

function questionTitle(step: StepId, answers: Answers): string {
  switch (step) {
    case 'purpose':
      return wizard.purpose.title;
    case 'frequency':
      return wizard.frequency.title;
    case 'payback':
      return answers.purpose === 'GAP' ? wizard.payback.titleGap : wizard.payback.title;
    case 'govContract':
      return wizard.govContract.title;
    case 'amount':
      return wizard.amount.title;
    case 'payment':
      return wizard.payment.title;
    case 'collateral':
      return wizard.collateral.title;
  }
}

/** Короткая подсказка под вопросом; у залога слово объясняется по наведению */
function StepHint({ step }: { step: StepId }) {
  switch (step) {
    case 'purpose':
      return <Text c="dimmed">{wizard.purpose.hint}</Text>;
    case 'frequency':
      return <Text c="dimmed">{wizard.frequency.hint}</Text>;
    case 'payback':
      return <Text c="dimmed">{wizard.payback.hint}</Text>;
    case 'govContract':
      return <Text c="dimmed">{wizard.govContract.hint}</Text>;
    case 'payment':
      return <Text c="dimmed">{wizard.payment.hint}</Text>;
    case 'collateral':
      return (
        <Text c="dimmed">
          <TermHint hint={termHints.collateral} />
          {wizard.collateral.hintTail}
        </Text>
      );
    case 'amount':
      return null;
  }
}
