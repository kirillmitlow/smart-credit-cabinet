import { documentTexts as dt } from '@/texts/documents';
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
  const raw = application.draft.collateral;
  const saved =
    raw &&
    typeof raw === 'object' &&
    'description' in raw &&
    'valueRub' in raw &&
    typeof raw.description === 'string' &&
    typeof raw.valueRub === 'number'
      ? { description: raw.description, valueRub: raw.valueRub }
      : null;
  const [collateral, setCollateral] = useState({
    enabled: !!saved,
    description: saved?.description ?? '',
    value: saved?.valueRub ?? 0,
  });
  const [contractNumber, setContractNumber] = useState(
    typeof application.draft.contractRegistryNumber === 'string'
      ? application.draft.contractRegistryNumber
      : '',
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
      <Title order={2}>{dt.productTitle}</Title>
      <Text>{dt.intro}</Text>
      {application.productCode === 'CONTRACT' ? (
        <TextInput
          label={dt.registryNumber}
          required
          maxLength={64}
          value={contractNumber}
          description={dt.registryHelp}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setContractNumber(value);
            autosave.schedule({ answers: { contractRegistryNumber: value.trim() } });
          }}
        />
      ) : null}
      <Checkbox
        label={dt.hasCollateral}
        checked={collateral.enabled}
        onChange={(event) =>
          changeCollateral({ ...collateral, enabled: event.currentTarget.checked })
        }
      />
      {collateral.enabled ? (
        <>
          <Textarea
            label={dt.description}
            required
            maxLength={500}
            value={collateral.description}
            onChange={(event) =>
              changeCollateral({ ...collateral, description: event.currentTarget.value })
            }
          />
          <NumberInput
            label={dt.value}
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
            {dt.disclaimer}
          </Text>
        </>
      ) : null}
      {!valid ? (
        <Text size="sm" c="red.9">
          {dt.required}
        </Text>
      ) : null}
      <DocumentFiles applicationId={application.id} disabled={autosave.state.kind === 'conflict'} />
    </Stack>
  );
}
