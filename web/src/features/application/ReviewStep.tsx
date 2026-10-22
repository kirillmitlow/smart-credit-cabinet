import { useRef, useState } from 'react';
import { Anchor, Button, Group, Stack, Text, Title, VisuallyHidden } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { listApplications, useSubmitApplication } from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { indicativePayment } from '@/lib/finance';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { applicationForm, fill, productName } from '@/texts';
import { missingFields } from './conditionsSchema';
import { isInFlight } from './statuses';
import { putApplication } from './useApplication';
import type { DraftAutosave } from './useDraftAutosave';

const r = applicationForm.review;

function SummaryRow({ label, value, to }: { label: string; value: string; to: string }) {
  return (
    <Group justify="space-between" wrap="nowrap" align="baseline">
      <Text c="dimmed">{label}</Text>
      <Group gap="md" wrap="nowrap">
        <Text fw={600}>{value}</Text>
        <Anchor component={Link} to={to} size="sm">
          {r.edit}
          <VisuallyHidden> {label.toLowerCase()}</VisuallyHidden>
        </Anchor>
      </Group>
    </Group>
  );
}

/** Шаг 5 «Проверьте и отправьте» (60-03 №7): сводка и «Отправить заявку» */
export function ReviewStep({
  application,
  autosave,
  onGoToStep,
}: {
  application: ApplicationOut;
  autosave: DraftAutosave;
  onGoToStep: (step: number) => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { role } = useActiveCompany();
  const action = useActionKey();
  const submit = useSubmitApplication({ request: action.request() });
  const [busy, setBusy] = useState(false);
  const submittingRef = useRef(false);

  const missing = missingFields(application);
  const canSubmit = application.allowedActions.includes('SUBMIT');
  const payment = indicativePayment(
    application.productCode,
    application.amountRub,
    application.termMonths,
  );
  const base = `/applications/${application.id}/edit`;

  const onSubmit = async () => {
    // двойной клик: второе нажатие не создаёт ещё одну отправку
    if (submittingRef.current) return;
    submittingRef.current = true;
    setBusy(true);
    try {
      const saved = await autosave.flush();
      if (!saved) return;
      await submit.mutateAsync(
        { applicationId: application.id },
        {
          onSuccess: (response) => {
            action.reset();
            if (response.status === 200) putApplication(queryClient, response.data);
            void queryClient.invalidateQueries({ queryKey: ['/applications'] });
            void navigate(`/applications/${application.id}`);
          },
        },
      );
    } catch {
      // ошибку показывает блок ниже (submit.error)
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  };

  /** Кнопка в сообщении об ошибке зависит от кода (60-06) */
  const onErrorAction = async () => {
    const code = isAppError(submit.error) ? submit.error.code : '';
    if (code === 'CONSENT_REQUIRED') {
      onGoToStep(4);
    } else if (code === 'DUPLICATE_APPLICATION') {
      let target = '/';
      try {
        const page = await listApplications({ limit: 100 });
        const other =
          page.status === 200
            ? page.data.items.find((item) => item.id !== application.id && isInFlight(item.status))
            : undefined;
        if (other) target = `/applications/${other.id}`;
      } catch {
        // не нашли — ведём к списку заявок на главной
      }
      void navigate(target);
    } else {
      submit.reset();
      await queryClient.invalidateQueries({ queryKey: [`/applications/${application.id}`] });
    }
  };

  return (
    <Stack gap="md" maw={520}>
      <Title order={2} size="h3">
        {r.heading}
      </Title>
      <Text c="dimmed">{r.hint}</Text>
      <Stack gap="xs" data-testid="review-summary">
        <SummaryRow
          label={r.product}
          value={productName(application.productCode) ?? r.notFilled}
          to={`${base}/1`}
        />
        <SummaryRow
          label={r.amount}
          value={application.amountRub ? formatMoney(application.amountRub) : r.notFilled}
          to={`${base}/1`}
        />
        <SummaryRow
          label={r.term}
          value={application.termMonths ? formatTermMonths(application.termMonths) : r.notFilled}
          to={`${base}/1`}
        />
        {payment === null ? null : (
          <Group justify="space-between" wrap="nowrap">
            <Text c="dimmed">{r.payment}</Text>
            <Text fw={600}>{formatMoney(payment)}</Text>
          </Group>
        )}
      </Stack>

      {missing.length > 0 ? (
        <Text role="alert" c="red.8">
          {fill(r.missing, {
            fields: missing.map((item) => r.missingNames[item]).join(', '),
          })}
        </Text>
      ) : null}
      {role === 'ACCOUNTANT' ? <Text size="sm">{r.accountantNote}</Text> : null}

      {submit.isError ? (
        <ProblemAlert
          error={submit.error}
          onAction={() => {
            void onErrorAction();
          }}
        />
      ) : null}

      {canSubmit ? (
        <Group>
          <Button
            onClick={() => {
              void onSubmit();
            }}
            disabled={missing.length > 0}
            loading={busy || submit.isPending}
          >
            {r.submit}
          </Button>
        </Group>
      ) : (
        <Text size="sm" c="dimmed">
          {r.noSubmitAction}
        </Text>
      )}
    </Stack>
  );
}
