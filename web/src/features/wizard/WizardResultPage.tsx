import { useRef, useState, type RefObject } from 'react';
import { Alert, Button, Card, Group, List, Stack, Text, Title } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router';
import {
  getApplication,
  useCreateApplication,
  usePatchApplicationDraft,
} from '@/api/generated/api';
import type { Recommended, RejectedCandidate, WizardResult } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { VariantCard } from '@/components/VariantCard';
import { putApplication } from '@/features/application/useApplication';
import { formatDateLong } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { fill, wizardResult as t } from '@/texts';
import { isResultLocationState, type Answers, type WizardLocationState } from './wizardModel';

/** Причины недоступности продукта: что случилось и что делать, без внутренних кодов */
function RejectedList({ rejected }: { rejected: readonly RejectedCandidate[] }) {
  if (rejected.length === 0) return null;
  return (
    <Stack gap="sm" component="section" aria-labelledby="wizard-rejected">
      <Title order={2} size="h3" id="wizard-rejected">
        {t.rejectedHeading}
      </Title>
      <Text c="dimmed">{t.rejectedIntro}</Text>
      <Stack component="ul" gap="sm" p={0} m={0} style={{ listStyle: 'none' }}>
        {rejected.map((candidate) => (
          <li key={candidate.productCode}>
            <Card withBorder padding="md" data-testid="rejected-candidate">
              <Stack gap={4}>
                <Text fw={600}>{candidate.title}</Text>
                <List size="sm" spacing={4} listStyleType="none" p={0}>
                  {candidate.reasons.map((reason) => (
                    <List.Item key={reason.code}>
                      <Text>{reason.text}</Text>
                      {reason.action ? (
                        <Text size="sm" c="dimmed">
                          {reason.action}
                        </Text>
                      ) : null}
                      {reason.availableFrom ? (
                        <Text size="sm" fw={600}>
                          {fill(t.rejectedAvailableFrom, {
                            date: formatDateLong(reason.availableFrom, { withYear: true }),
                          })}
                        </Text>
                      ) : null}
                    </List.Item>
                  ))}
                </List>
              </Stack>
            </Card>
          </li>
        ))}
      </Stack>
    </Stack>
  );
}

/** Карточка продукта из ответа подбора; числа берём как есть, срок и сумму — из ответов клиента */
function RecommendedCard({
  rec,
  answers,
  primary,
  applying,
  onApply,
}: {
  rec: Recommended;
  answers: Answers;
  primary: boolean;
  applying: boolean;
  onApply: (rec: Recommended, isPrimary: boolean) => void;
}) {
  const termMonths = answers.termMonths ?? null;
  const chosen = rec.comfortableOptions.find((option) => option.termMonths === termMonths);
  return (
    <VariantCard
      id={`wizard-${rec.productCode.toLowerCase()}`}
      title={rec.title}
      headingLevel={3}
      recommended={primary}
      why={rec.why}
      amountRub={answers.amountRub ?? null}
      termMonths={termMonths}
      paymentRub={rec.paymentRub}
      paymentKind={rec.paymentKind}
      overpaymentRub={chosen?.overpaymentRub ?? null}
      ratePercentFrom={rec.ratePercentFrom}
      approximate={rec.approximate ?? true}
      decisionTime={rec.decisionTime}
      documents={rec.documents}
      needsCollateral={rec.needsCollateral}
      needsContract={rec.needsContract}
      needsSecurity={rec.requiresSecurity}
      comfortableOptions={rec.comfortableOptions}
      actions={
        <div>
          <Button
            variant={primary ? 'filled' : 'default'}
            loading={applying}
            onClick={() => onApply(rec, primary)}
          >
            {t.apply}
          </Button>
        </div>
      }
    />
  );
}

/**
 * Результат подбора (60-03 №5): основной вариант и одна альтернатива, либо «что станет доступно
 * и когда». «Оформить заявку» ведёт на шаг «Условия» с подставленными продуктом, суммой и сроком.
 * Ответы и результат приходят из мастера в состоянии адреса и переживают перезагрузку страницы.
 */
export function WizardResultPage() {
  const location = useLocation();
  const state = isResultLocationState(location.state) ? location.state : null;
  const headingRef = usePageHeading(state ? t.title : t.noAnswers);

  if (!state) {
    return (
      <Stack gap="md" align="flex-start">
        <Title order={1} size="h2" ref={headingRef} tabIndex={-1}>
          {t.noAnswers}
        </Title>
        <Button component={Link} to="/wizard">
          {t.startAgain}
        </Button>
      </Stack>
    );
  }
  return <ResultView state={state} result={state.result} headingRef={headingRef} />;
}

function ResultView({
  state,
  result,
  headingRef,
}: {
  state: WizardLocationState;
  result: WizardResult;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const action = useActionKey();
  const create = useCreateApplication({ request: action.request() });
  const patch = usePatchApplicationDraft();
  const [applying, setApplying] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const busyRef = useRef(false);
  const { answers } = state;
  const draftId = state.applicationId ?? result.applicationId ?? null;

  /**
   * Мастер уже создал черновик и положил в него основной продукт, сумму и срок. Для основного
   * варианта остаётся открыть форму; для запасного меняем продукт в черновике (`PATCH …/draft`).
   */
  const apply = async (rec: Recommended, isPrimary: boolean) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setApplying(rec.productCode);
    setError(null);
    try {
      let id = draftId;
      let version = 0;
      let needsPatch = !isPrimary;
      if (id === null) {
        const created = await create.mutateAsync({ data: {} });
        if (created.status !== 201) return;
        action.reset();
        id = created.data.id;
        version = created.data.version;
        putApplication(queryClient, created.data);
        needsPatch = true;
      }
      if (needsPatch) {
        if (version === 0) {
          const current = await getApplication(id);
          if (current.status !== 200) return;
          version = current.data.version;
        }
        const saved = await patch.mutateAsync({
          applicationId: id,
          data: {
            version,
            productCode: rec.productCode,
            ...(typeof answers.amountRub === 'number' ? { amountRub: answers.amountRub } : {}),
            ...(typeof answers.termMonths === 'number' ? { termMonths: answers.termMonths } : {}),
            answers: {},
          },
        });
        if (saved.status !== 200) return;
        putApplication(queryClient, saved.data);
      }
      void queryClient.invalidateQueries({ queryKey: ['/applications'] });
      void navigate(`/applications/${id}/edit/1`);
    } catch (caught) {
      setError(caught);
    } finally {
      busyRef.current = false;
      setApplying(null);
    }
  };

  const changeAnswers = () => {
    const back: WizardLocationState = { answers, applicationId: draftId };
    void navigate('/wizard', { state: back });
  };

  const hasVariants = result.outcome === 'RECOMMENDED' && result.primary !== null;

  return (
    <Stack gap="xl">
      <Stack gap={4}>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {hasVariants ? t.title : t.noneTitle}
        </Title>
        {hasVariants ? (
          <Text c="dimmed">{result.alternative ? t.intro : t.introSingle}</Text>
        ) : null}
      </Stack>

      {result.startPath ? (
        <Alert color="gray" variant="light" title={t.startPath.heading} data-testid="start-path">
          {t.startPath.body}
        </Alert>
      ) : null}

      {hasVariants && result.primary ? (
        <Stack gap="lg">
          <Stack gap="sm" component="section" aria-labelledby="wizard-primary">
            <Title order={2} size="h3" id="wizard-primary">
              {t.primaryHeading}
            </Title>
            <RecommendedCard
              rec={result.primary}
              answers={answers}
              primary
              applying={applying === result.primary.productCode}
              onApply={(rec, isPrimary) => void apply(rec, isPrimary)}
            />
          </Stack>
          {result.alternative ? (
            <Stack gap="sm" component="section" aria-labelledby="wizard-alternative">
              <Title order={2} size="h3" id="wizard-alternative">
                {t.alternativeHeading}
              </Title>
              <RecommendedCard
                rec={result.alternative}
                answers={answers}
                primary={false}
                applying={applying === result.alternative.productCode}
                onApply={(rec, isPrimary) => void apply(rec, isPrimary)}
              />
            </Stack>
          ) : null}
        </Stack>
      ) : (
        <Stack gap="sm" maw={640} data-testid="catalog-hint">
          {result.hint ? <Text size="lg">{result.hint}</Text> : null}
          <Text c="dimmed">{t.noneNext}</Text>
          <Button component={Link} to="/products" variant="light">
            {t.openCatalog}
          </Button>
        </Stack>
      )}

      {hasVariants && result.hint ? (
        <Alert color="blue" variant="light" title={t.futureHeading} data-testid="future-hint">
          {result.hint}
        </Alert>
      ) : null}

      <RejectedList rejected={result.rejected} />

      {error ? <ProblemAlert error={error} /> : null}

      <Group>
        <Button variant="default" onClick={changeAnswers}>
          {t.changeAnswers}
        </Button>
      </Group>
    </Stack>
  );
}
