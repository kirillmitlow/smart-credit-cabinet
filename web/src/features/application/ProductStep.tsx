import { useEffect, useState } from 'react';
import { Checkbox, NumberInput, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import type { ApplicationOut } from '@/api/generated/model';
import type { DraftAutosave } from './useDraftAutosave';
import { DocumentFiles } from './DocumentFiles';

export function ProductStep({
  application,
  autosave,
  onValidityChange,
}: {
  application: ApplicationOut;
  autosave: DraftAutosave;
  onValidityChange: (valid: boolean) => void;
}) {
  const saved = application.draft.collateral as { description?: string; valueRub?: number } | null;
  const [collateral, setCollateral] = useState({
    enabled: !!saved,
    description: saved?.description ?? '',
    value: saved?.valueRub ?? 0,
  });
  const [contractNumber, setContractNumber] = useState(
    String(application.draft.contractRegistryNumber ?? ''),
  );
  const valid =
    (!collateral.enabled || (collateral.description.trim().length > 0 && collateral.value > 0)) &&
    (application.productCode !== 'CONTRACT' || contractNumber.trim().length > 0);
  useEffect(() => {
    onValidityChange(valid);
  }, [onValidityChange, valid]);

  const changeCollateral = (next: typeof collateral) => {
    setCollateral(next);
    if (!next.enabled || (next.description.trim() && next.value > 0)) {
      autosave.schedule({
        answers: {
          collateral: next.enabled
            ? { description: next.description.trim(), valueRub: next.value }
            : null,
        },
      });
    }
  };
  return (
    <Stack gap="md">
      <Title order={2}>Что нужно для продукта</Title>
      <Text>Прикрепите подтверждающие документы и укажите обеспечение, если оно есть.</Text>
      {application.productCode === 'CONTRACT' ? (
        <TextInput
          label="Реестровый номер госконтракта"
          required
          maxLength={64}
          value={contractNumber}
          description="Укажите номер контракта вашей компании из ЕИС. Банк проверит его по источнику."
          onChange={(event) => {
            const value = event.currentTarget.value;
            setContractNumber(value);
            autosave.schedule({ answers: { contractRegistryNumber: value.trim() } });
          }}
        />
      ) : null}
      <Checkbox
        label="Предлагаю имущество в залог"
        checked={collateral.enabled}
        onChange={(event) =>
          changeCollateral({ ...collateral, enabled: event.currentTarget.checked })
        }
      />
      {collateral.enabled ? (
        <>
          <Textarea
            label="Описание залога"
            required
            maxLength={500}
            value={collateral.description}
            onChange={(event) =>
              changeCollateral({ ...collateral, description: event.currentTarget.value })
            }
          />
          <NumberInput
            label="Ваша оценка стоимости залога, ₽"
            required
            min={1}
            max={1_000_000_000}
            allowDecimal={false}
            allowNegative={false}
            thousandSeparator=" "
            value={collateral.value || ''}
            onChange={(value) => changeCollateral({ ...collateral, value: Number(value) || 0 })}
          />
          <Text size="sm" c="dimmed">
            Это ваша оценка. Сотрудник банка рассматривает залог отдельно; автоматическим
            подтверждением она не является.
          </Text>
        </>
      ) : null}
      {!valid ? (
        <Text size="sm" c="red.9">
          Заполните обязательные сведения, чтобы продолжить.
        </Text>
      ) : null}
      <DocumentFiles applicationId={application.id} disabled={autosave.state.kind === 'conflict'} />
    </Stack>
  );
}
