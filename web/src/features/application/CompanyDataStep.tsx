import { useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  CloseButton,
  Group,
  Loader,
  Paper,
  Popover,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import {
  getGetCompanyProfileQueryKey,
  lookupCompany,
  useGetCompanyProfile,
} from '@/api/generated/api';
import type { ApplicationOut, CompanyProfile, ProfileField } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatDateTime } from '@/lib/format';
import { fill } from '@/texts';
import { companyProfile as t } from '@/texts/companyProfile';
import type { DraftAutosave } from './useDraftAutosave';

const READ_ONLY = new Set(['inn', 'status', 'isBankCustomer', 'customerSince']);

function display(value: ProfileField['value']): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? t.yes : t.no;
  if (typeof value === 'string' && Object.hasOwn(t.values, value))
    return t.values[value as keyof typeof t.values];
  return String(value);
}

function Source({ name, field, manual }: { name: string; field: ProfileField; manual: boolean }) {
  const [opened, setOpened] = useState(false);
  return (
    <Popover withArrow trapFocus returnFocus opened={opened} onChange={setOpened}>
      <Popover.Target>
        <Button
          type="button"
          size="compact-xs"
          variant="subtle"
          aria-label={fill(t.source, { field: name })}
          onClick={() => setOpened((value) => !value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpened(false);
          }}
        >
          {t.from}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs" maw={320}>
          <Group justify="space-between">
            <Text fw={600}>{t.sourceNames[field.source]}</Text>
            <CloseButton
              aria-label={t.closeSource}
              data-autofocus
              onClick={() => setOpened(false)}
            />
          </Group>
          <Text size="sm">
            {field.retrievedAt
              ? fill(t.received, { date: formatDateTime(field.retrievedAt) })
              : t.unavailable}
          </Text>
          {manual ? (
            <Text size="sm">{fill(t.original, { value: display(field.value) || t.empty })}</Text>
          ) : null}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

function savedFields(application: ApplicationOut): Record<string, string> {
  const raw = application.draft.companyFields;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw)
      .filter(
        ([key, v]) => typeof v === 'string' && !READ_ONLY.has(key) && Object.hasOwn(t.labels, key),
      )
      .map(([k, v]) => [k, String(v)]),
  );
}

function Fields({
  view,
  application,
  autosave,
}: {
  view: CompanyProfile;
  application: ApplicationOut;
  autosave: DraftAutosave;
}) {
  const [changes, setChanges] = useState(() => savedFields(application));
  const entries = Object.entries(t.labels).flatMap(([key, label]) => {
    const field = view.fields[key];
    return field ? [{ key, label, field }] : [];
  });
  const count = entries.filter(
    ({ key, field }) =>
      field.confirmed &&
      field.value !== null &&
      field.value !== undefined &&
      !Object.hasOwn(changes, key),
  ).length;
  const sources = Object.entries(t.sourceNames).flatMap(([source, label]) => {
    const fields = entries.filter(({ field }) => field.source === source);
    if (!fields.length) return [];
    const latest = fields
      .flatMap(({ field }) => (field.retrievedAt ? [field.retrievedAt] : []))
      .sort()
      .at(-1);
    const confirmed = fields.filter(
      ({ key, field }) => field.confirmed && field.value != null && !Object.hasOwn(changes, key),
    ).length;
    return [{ source, label, latest, confirmed }];
  });
  const change = (key: string, value: string, original: ProfileField['value']) => {
    const next = { ...changes };
    if (value === display(original)) delete next[key];
    else next[key] = value;
    setChanges(next);
    autosave.schedule({ answers: { companyFields: next } });
  };
  return (
    <Stack gap="md">
      <Paper withBorder p="md">
        <Stack gap="xs">
          <Text fw={500}>{fill(t.summary, { count })}</Text>
          <Group>
            {sources.map(({ source, label, latest, confirmed }) => (
              <Stack key={source} gap={2}>
                <Text size="sm">
                  {label}: {confirmed}
                </Text>
                <Text size="xs" c="dimmed">
                  {latest ? fill(t.received, { date: formatDateTime(latest) }) : t.unavailable}
                </Text>
              </Stack>
            ))}
          </Group>
        </Stack>
      </Paper>
      {entries.map(({ key, label, field }) => {
        const manual = Object.hasOwn(changes, key);
        return (
          <Stack gap={4} key={key}>
            <TextInput
              label={label}
              value={manual ? (changes[key] ?? '') : display(field.value)}
              readOnly={READ_ONLY.has(key)}
              maxLength={500}
              onChange={(event) => change(key, event.currentTarget.value, field.value)}
            />
            <Group gap="xs">
              <Badge
                variant="light"
                color={manual ? 'blue' : field.confirmed ? 'green' : 'gray'}
                styles={{ label: { color: 'var(--mantine-color-text)' } }}
              >
                {manual ? t.manual : field.confirmed ? t.confirmed : t.unconfirmed}
              </Badge>
              <Source name={label} field={field} manual={manual} />
            </Group>
          </Stack>
        );
      })}
      <Text size="sm" c="dimmed">
        {t.manualHint}
      </Text>
    </Stack>
  );
}

export function CompanyDataStep({
  application,
  autosave,
}: {
  application: ApplicationOut;
  autosave: DraftAutosave;
}) {
  const client = useQueryClient();
  const query = useGetCompanyProfile(application.companyId, {
    query: { select: (r) => (r.status === 200 ? r.data : undefined) },
  });
  const view = query.data;
  const refresh = useMutation({
    mutationFn: async () => {
      if (!view) return;
      const response = await lookupCompany(view.inn);
      if (response.status === 200)
        client.setQueryData(getGetCompanyProfileQueryKey(application.companyId), response);
    },
  });
  if (!view)
    return query.isPending ? (
      <Group role="status">
        <Loader size="sm" />
        <Text>{t.loading}</Text>
      </Group>
    ) : (
      <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
    );
  return (
    <Stack gap="md" maw={720}>
      <Title order={2} size="h3">
        {t.heading}
      </Title>
      {query.isError ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {view.eligibility === 'NOT_ELIGIBLE' ? <Alert color="yellow">{t.notEligible}</Alert> : null}
      {view.eligibility === 'COMPANY_NOT_ACTIVE' ? (
        <Alert color="yellow">{t.inactive}</Alert>
      ) : null}
      {view.eligibility === 'UNCONFIRMED' ? <Alert color="gray">{t.unknown}</Alert> : null}
      {view.relatedCompanies.length ? (
        <Alert color="blue">
          <Stack gap="xs">
            <Text>{t.related}</Text>
            {view.relatedCompanies.map((c) => (
              <Text key={c.id}>{c.name}</Text>
            ))}
            <Anchor component={Link} to="/company">
              {t.chooseCompany}
            </Anchor>
          </Stack>
        </Alert>
      ) : null}
      <Fields view={view} application={application} autosave={autosave} />
      {refresh.error ? <ProblemAlert error={refresh.error} /> : null}
      <div>
        <Button variant="light" loading={refresh.isPending} onClick={() => refresh.mutate()}>
          {t.refresh}
        </Button>
      </div>
    </Stack>
  );
}
