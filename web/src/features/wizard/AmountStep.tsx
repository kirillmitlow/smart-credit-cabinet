import { useState } from 'react';
import { Alert, Button, Group, NumberInput, Stack, Text } from '@mantine/core';
import { MAX_AMOUNT_RUB } from '@/features/application/conditionsSchema';
import { NBSP } from '@/lib/format';
import { applicationForm, wizard } from '@/texts';

const t = wizard.amount;
const v = applicationForm.validation;

/** Понятная ошибка суммы или `null`, если сумма подходит */
function amountProblem(value: number | string): string | null {
  if (value === '') return v.amountRequired;
  if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) return v.amountInvalid;
  if (value > MAX_AMOUNT_RUB) return v.amountTooBig;
  return null;
}

/**
 * Вопрос про сумму (10-07): поле числа. «Не знаю» показывает подсказку («сколько обычно
 * закупаете в месяц?») и позволяет продолжить без суммы: подбор идёт без этого ответа.
 */
export function AmountStep({
  initial,
  disabled,
  onSubmit,
}: {
  initial: number | null | undefined;
  disabled: boolean;
  /** Число рублей или `null` — «Не знаю» */
  onSubmit: (amountRub: number | null) => void;
}) {
  const [value, setValue] = useState<number | string>(initial ?? '');
  const [touched, setTouched] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const problem = amountProblem(value);

  return (
    <Stack
      component="form"
      gap="md"
      maw={520}
      {...{ noValidate: true }}
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        if (problem === null && !disabled) onSubmit(Number(value));
      }}
    >
      <NumberInput
        label={t.label}
        description={t.hint}
        required
        allowDecimal={false}
        allowNegative={false}
        thousandSeparator={NBSP}
        hideControls
        inputMode="numeric"
        value={value}
        onChange={setValue}
        onBlur={() => setTouched(true)}
        error={touched ? problem : null}
      />
      <Group>
        <Button type="submit" disabled={disabled}>
          {t.next}
        </Button>
        <Button
          type="button"
          variant="subtle"
          disabled={disabled}
          aria-expanded={helpOpen}
          onClick={() => setHelpOpen(true)}
        >
          {wizard.unknown}
        </Button>
      </Group>
      {helpOpen ? (
        <Alert color="gray" variant="light" title={t.help.heading} role="status">
          <Stack gap="sm" align="flex-start">
            <Text>{t.help.body}</Text>
            <Button
              type="button"
              variant="default"
              disabled={disabled}
              onClick={() => onSubmit(null)}
            >
              {t.help.skip}
            </Button>
          </Stack>
        </Alert>
      ) : null}
    </Stack>
  );
}
