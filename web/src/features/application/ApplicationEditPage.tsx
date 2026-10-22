import { useCallback, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Button, Center, Loader, Stack, Stepper, Text, Title } from '@mantine/core';
import { useForm, type Resolver } from 'react-hook-form';
import { Navigate, useNavigate, useParams } from 'react-router';
import { NotFoundScreen } from '@/app/screens';
import { AppError, isAppError } from '@/api/errors';
import { ErrorScreen } from '@/components/ErrorScreen';
import { ProblemAlert } from '@/components/ProblemAlert';
import { usePageHeading } from '@/lib/usePageHeading';
import { applicationForm, errorView, fill, guards } from '@/texts';
import { ConditionsStep } from './ConditionsStep';
import { ConsentsStep } from './ConsentsStep';
import { CompanyDataStep } from './CompanyDataStep';
import { conditionsSchema, toForm, type ConditionsForm } from './conditionsSchema';
import { LaterStep } from './LaterStep';
import { ReviewStep } from './ReviewStep';
import { SaveStatusLine } from './SaveStatusLine';
import { useApplication } from './useApplication';
import { useDraftAutosave } from './useDraftAutosave';
import type { ApplicationOut } from '@/api/generated/model';

const STEP_COUNT = 5;
const stepTitles = [
  applicationForm.steps.conditions,
  applicationForm.steps.company,
  applicationForm.steps.product,
  applicationForm.steps.consents,
  applicationForm.steps.review,
] as const;

function parseStep(raw: string | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const step = Number(raw);
  return step >= 1 && step <= STEP_COUNT ? step : null;
}

const conflictError = new AppError({ code: 'VERSION_CONFLICT', status: 409, requestId: null });

/** Внутренняя часть: черновик уже загружен, форма и автосохранение живут здесь */
function EditForm({
  application,
  step,
  refresh,
}: {
  application: ApplicationOut;
  step: number;
  refresh: () => Promise<ApplicationOut | undefined>;
}) {
  const navigate = useNavigate();
  const form = useForm<ConditionsForm>({
    resolver: zodResolver(conditionsSchema) as unknown as Resolver<ConditionsForm>,
    mode: 'onChange',
    defaultValues: toForm(application),
  });
  const autosave = useDraftAutosave(application);
  const [formRevision, setFormRevision] = useState({ revision: 0, snapshot: application });
  const { flush, clearConflict } = autosave;
  const title = fill(applicationForm.stepOf, {
    current: step,
    total: STEP_COUNT,
    title: stepTitles[step - 1] ?? '',
  });
  const headingRef = usePageHeading(title);

  const goToStep = useCallback(
    (next: number) => {
      void flush().then((saved) => {
        if (saved) void navigate(`/applications/${application.id}/edit/${next}`);
      });
    },
    [flush, navigate, application.id],
  );

  const onRefresh = () => {
    void refresh().then((fresh) => {
      if (fresh) {
        form.reset(toForm(fresh));
        // refetch resolves before React Query notifies the parent; initialize fields from its actual answer.
        setFormRevision((old) => ({ revision: old.revision + 1, snapshot: fresh }));
        clearConflict();
      }
    });
  };

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          {applicationForm.title}
        </Text>
        <Title order={1} ref={headingRef} tabIndex={-1}>
          {title}
        </Title>
        <Text size="sm" c="dimmed">
          {application.number}
        </Text>
      </Stack>

      <nav aria-label={applicationForm.stepsLabel}>
        <Stepper
          active={step - 1}
          onStepClick={(index) => goToStep(index + 1)}
          allowNextStepsSelect
          size="sm"
        >
          {stepTitles.map((label) => (
            <Stepper.Step key={label} label={label} />
          ))}
        </Stepper>
      </nav>

      {autosave.state.kind === 'conflict' ? (
        <ProblemAlert error={conflictError} onAction={onRefresh} />
      ) : null}

      {step === 1 ? <ConditionsStep form={form} autosave={autosave} /> : null}
      {step === 2 ? (
        <CompanyDataStep
          key={`${application.id}:${formRevision.revision}`}
          application={
            formRevision.snapshot.version > application.version
              ? formRevision.snapshot
              : application
          }
          autosave={autosave}
        />
      ) : null}
      {step === 3 ? (
        <LaterStep title={applicationForm.steps.product} body={applicationForm.later.product} />
      ) : null}
      {step === 4 ? <ConsentsStep key={application.id} applicationId={application.id} /> : null}
      {step === 5 ? (
        <ReviewStep application={application} autosave={autosave} onGoToStep={goToStep} />
      ) : null}

      <SaveStatusLine
        state={autosave.state}
        onRetry={() => {
          void flush();
        }}
      />

      <div>
        {step > 1 ? (
          <Button variant="default" mr="sm" onClick={() => goToStep(step - 1)}>
            {applicationForm.back}
          </Button>
        ) : null}
        {step < STEP_COUNT ? (
          <Button onClick={() => goToStep(step + 1)}>{applicationForm.next}</Button>
        ) : null}
      </div>
    </Stack>
  );
}

/**
 * Заявка по шагам (60-03 №7): `/applications/:id/edit/:step`. Шаг в адресе, поэтому «назад»
 * браузера работает. Отправленная заявка не редактируется: ведём на её страницу.
 */
export function ApplicationEditPage() {
  const { id = '', step: rawStep } = useParams();
  const step = parseStep(rawStep);
  const query = useApplication(id);
  const application = query.data;
  const refetch = query.refetch;

  const refresh = useCallback(async () => {
    const result = await refetch();
    return result.isSuccess ? result.data : undefined;
  }, [refetch]);

  if (step === null) return <NotFoundScreen />;
  if (query.isPending) {
    return (
      <Center py="xl" role="status">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {applicationForm.loading}
          </Text>
        </Stack>
      </Center>
    );
  }
  if (!application) {
    if (isAppError(query.error) && query.error.status === 404) {
      return <NotFoundScreen kind="application" />;
    }
    const view = errorView(query.error);
    return (
      <ErrorScreen
        title={guards.generalError.title}
        body={view.text}
        requestId={view.requestId}
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }
  if (application.status !== 'DRAFT') return <Navigate to={`/applications/${id}`} replace />;
  return <EditForm key={application.id} application={application} step={step} refresh={refresh} />;
}
