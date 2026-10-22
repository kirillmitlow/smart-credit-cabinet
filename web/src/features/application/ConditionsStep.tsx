import { useEffect } from 'react';
import { Button, Group, NumberInput, Select, Stack, Text, Title } from '@mantine/core';
import { Controller, useWatch, type UseFormReturn } from 'react-hook-form';
import { Link } from 'react-router';
import { NBSP, formatMoney } from '@/lib/format';
import { indicativePayment } from '@/lib/finance';
import { applicationForm, productNames } from '@/texts';
import { productCodes, validFields, type ConditionsForm } from './conditionsSchema';
import type { DraftAutosave } from './useDraftAutosave';

const c = applicationForm.conditions;

const productOptions = productCodes.map((code) => ({ value: code, label: productNames[code] }));

/** Шаг 1 «Условия» (60-03 №7): продукт, сумма, срок; платёж пересчитывается сразу */
export function ConditionsStep({
  form,
  autosave,
}: {
  form: UseFormReturn<ConditionsForm>;
  autosave: DraftAutosave;
}) {
  const { control, watch } = form;
  const { schedule } = autosave;
  const values = useWatch({ control });

  // Автосохранение запускают только правки человека (`type: 'change'`): подстановка значений его не будит
  useEffect(() => {
    const subscription = watch((current, info) => {
      if (info.type === 'change') schedule(validFields(current));
    });
    return () => subscription.unsubscribe();
  }, [watch, schedule]);

  const payment = indicativePayment(
    values.productCode,
    typeof values.amountRub === 'number' ? values.amountRub : null,
    typeof values.termMonths === 'number' ? values.termMonths : null,
  );

  return (
    <Stack gap="md" maw={520}>
      <Title order={2} size="h3">
        {c.heading}
      </Title>
      <Text c="dimmed">{c.hint}</Text>
      <Controller
        control={control}
        name="productCode"
        render={({ field, fieldState }) => (
          <Select
            label={c.product}
            placeholder={c.productPlaceholder}
            data={productOptions}
            allowDeselect={false}
            required
            value={field.value === '' ? null : field.value}
            onChange={(value) => field.onChange(value ?? '')}
            onBlur={field.onBlur}
            error={fieldState.error?.message}
          />
        )}
      />
      <Controller
        control={control}
        name="amountRub"
        render={({ field, fieldState }) => (
          <NumberInput
            label={c.amount}
            description={c.amountHint}
            required
            allowDecimal={false}
            allowNegative={false}
            thousandSeparator={NBSP}
            hideControls
            inputMode="numeric"
            value={field.value}
            onChange={field.onChange}
            onBlur={field.onBlur}
            error={fieldState.error?.message}
          />
        )}
      />
      <Controller
        control={control}
        name="termMonths"
        render={({ field, fieldState }) => (
          <NumberInput
            label={c.term}
            description={c.termHint}
            required
            allowDecimal={false}
            allowNegative={false}
            hideControls
            inputMode="numeric"
            value={field.value}
            onChange={field.onChange}
            onBlur={field.onBlur}
            error={fieldState.error?.message}
          />
        )}
      />
      <Stack gap={2} aria-live="polite" data-testid="payment">
        <Text size="sm" c="dimmed">
          {c.paymentLabel}
        </Text>
        <Text fw={700} size="xl">
          {payment === null ? c.paymentLater : formatMoney(payment)}
        </Text>
        {payment === null ? null : (
          <Text size="sm" c="dimmed">
            {c.paymentNote}
          </Text>
        )}
      </Stack>
      <Group gap="xs" align="baseline">
        <Button component={Link} to="/wizard" variant="subtle" px={0}>
          {c.pickWizard}
        </Button>
        <Text size="sm" c="dimmed">
          {c.pickWizardHint}
        </Text>
      </Group>
    </Stack>
  );
}
