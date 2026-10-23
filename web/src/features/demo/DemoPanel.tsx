import { useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Button,
  Group,
  Modal,
  Paper,
  PasswordInput,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { bankDemoLogin, demoReset, demoResetPersona } from '@/api/generated/api';
import type { Persona } from '@/api/generated/model';
import { appErrorFromResponse, isAppError } from '@/api/errors';
import { readCookie } from '@/api/client';
import { sessionQueryKey } from '@/api/session-keys';
import { ProblemAlert } from '@/components/ProblemAlert';
import { usePublicConfig } from '@/features/auth/session';
import { productNames } from '@/texts/application';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { demo as t } from '@/texts/demo';
import { usePersonas } from './api';
import { DemoChaos } from './DemoChaos';
import { outcome } from './formatting';

function PersonaCard({ persona: p, onReset }: { persona: Persona; onReset: () => void }) {
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Title order={3} size="h4">
          {p.title}
        </Title>
        <Text size="sm">
          {t.inn}: {p.inn ?? t.unknown}
        </Text>
        {p.application ? (
          <Text size="sm">
            {t.request}:{' '}
            {productNames[p.application.productCode as keyof typeof productNames] ??
              p.application.productCode ??
              t.unknown}{' '}
            · {formatMoney(Number(p.application.amountRub))} ·{' '}
            {formatTermMonths(p.application.termMonths)}
          </Text>
        ) : null}
        <Text>
          {t.expected}: {outcome(p.expectedOutcome)}
        </Text>
        {p.expectedFinalOutcome ? (
          <Text size="sm">
            {t.final}: {outcome(p.expectedFinalOutcome)}
          </Text>
        ) : null}
        {p.expectedReasonCodes?.length ? (
          <Text size="sm">
            {t.reasons}: {p.expectedReasonCodes.join(', ')}
          </Text>
        ) : null}
        {p.status !== 'APPLIED' ? <Text c="dimmed">{t.unapplied}</Text> : null}
        <Button variant="light" color="red" onClick={onReset} disabled={!p.companyId}>
          {t.resetOne}
        </Button>
      </Stack>
    </Paper>
  );
}

export function DemoPanel({ onResetAll }: { onResetAll?: () => void }) {
  const config = usePublicConfig().data;
  const personas = usePersonas();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [code, setCode] = useState('');
  const [target, setTarget] = useState<Persona | 'all' | null>(null);
  const [receipt, setReceipt] = useState<string[]>([]);
  const [popupError, setPopupError] = useState(false);
  const reset = useMutation({
    mutationFn: async (value: Persona | 'all') => {
      const options = { headers: { 'X-Demo-Code': code } };
      const r =
        value === 'all' ? await demoReset(options) : await demoResetPersona(value.code, options);
      if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
      return r.data;
    },
    onSuccess: (data, value) => {
      setReceipt(data.steps.map((s) => s.title));
      setTarget(null);
      if (value === 'all') {
        onResetAll?.();
        cache.clear();
        void navigate('/login');
      } else void cache.invalidateQueries();
    },
  });
  const login = useMutation({
    mutationFn: async ({ role, tab }: { role: 'UNDERWRITER' | 'ADMIN'; tab: Window }) => {
      try {
        const r = await bankDemoLogin(
          { role },
          { headers: { 'X-CSRF-Token': readCookie('csrf_bank') ?? '' } },
        );
        if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
        cache.setQueryData(sessionQueryKey('bank'), {
          ...r.data,
          activeCompanyId: null,
          companies: [],
        });
        tab.location.href = '/bank';
      } catch (e) {
        tab.close();
        throw e;
      }
    },
  });
  const enter = (role: 'UNDERWRITER' | 'ADMIN') => {
    const tab = window.open('about:blank', '_blank');
    setPopupError(!tab);
    if (tab) {
      tab.opener = null;
      login.mutate({ role, tab });
    }
  };
  const failedStep = isAppError(reset.error) ? reset.error.errors[0]?.code : null;
  const stepLabel = failedStep ? t.resetSteps[failedStep as keyof typeof t.resetSteps] : null;
  const links = Object.entries(config?.docsLinks ?? {}).filter(([, url]) =>
    /^(https?:\/\/|\/(?!\/))/.test(url),
  );
  return (
    <Stack gap="lg">
      <Title order={1}>{t.title}</Title>
      <Alert color="yellow">{t.shared}</Alert>
      <Group>
        <Button onClick={() => enter('UNDERWRITER')} loading={login.isPending}>
          {t.bank}
        </Button>
        <Button variant="light" onClick={() => enter('ADMIN')} disabled={login.isPending}>
          {t.admin}
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {t.bankHelp}
      </Text>
      {popupError ? (
        <Alert color="red" role="alert">
          {t.popup}
        </Alert>
      ) : null}
      {login.isError ? <ProblemAlert error={login.error} /> : null}
      <Anchor component={Link} to="/bank" target="_blank">
        {t.outbox}
      </Anchor>
      {config?.demoCodeRequired ? (
        <PasswordInput
          label={t.code}
          description={t.codeHelp}
          value={code}
          onChange={(e) => setCode(e.currentTarget.value)}
          autoComplete="off"
        />
      ) : null}
      <Button
        color="red"
        variant="light"
        onClick={() => {
          reset.reset();
          setTarget('all');
        }}
      >
        {t.resetAll}
      </Button>
      {receipt.length ? (
        <Alert color="green" role="status">
          {t.resetDone}: {receipt.join(' → ')}
        </Alert>
      ) : null}
      <Title order={2}>{t.guide}</Title>
      <Text>{t.help}</Text>
      {personas.isPending ? <Text role="status">{t.refresh}…</Text> : null}
      {personas.isError ? (
        <ProblemAlert error={personas.error} onAction={() => void personas.refetch()} />
      ) : null}
      {personas.data?.length === 0 ? <Text>{t.empty}</Text> : null}
      {personas.data
        ?.filter((p) => !p.technical)
        .map((p) => (
          <PersonaCard
            key={p.code}
            persona={p}
            onReset={() => {
              reset.reset();
              setTarget(p);
            }}
          />
        ))}
      {personas.data?.some((p) => p.technical) ? (
        <Accordion>
          <Accordion.Item value="technical">
            <Accordion.Control>{t.technical}</Accordion.Control>
            <Accordion.Panel>
              <Stack>
                {personas.data
                  .filter((p) => p.technical)
                  .map((p) => (
                    <PersonaCard
                      key={p.code}
                      persona={p}
                      onReset={() => {
                        reset.reset();
                        setTarget(p);
                      }}
                    />
                  ))}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      ) : null}
      <DemoChaos code={code} />
      <Title order={2}>{t.docs}</Title>
      {links.map(([name, url]) => (
        <Anchor key={name} href={url} target="_blank" rel="noopener noreferrer">
          {name}
        </Anchor>
      ))}
      {links.length < 5 ? (
        <Text size="sm" c="dimmed">
          {t.noDocs}
        </Text>
      ) : null}
      <Modal
        closeButtonProps={{ 'aria-label': t.close }}
        opened={target !== null}
        onClose={() => {
          if (!reset.isPending) setTarget(null);
        }}
        title={target === 'all' ? t.resetAll : target?.title}
        closeOnClickOutside={!reset.isPending}
        closeOnEscape={!reset.isPending}
        withCloseButton={!reset.isPending}
      >
        <Stack>
          <Text>{target === 'all' ? t.allWarning : t.oneWarning}</Text>
          {reset.isError ? <ProblemAlert error={reset.error} /> : null}
          {stepLabel ? (
            <Text role="status">
              {t.failedAt}: {stepLabel}
            </Text>
          ) : null}
          {reset.isPending ? <Text role="status">{t.resetting}</Text> : null}
          <Group>
            <Button variant="default" disabled={reset.isPending} onClick={() => setTarget(null)}>
              {t.cancel}
            </Button>
            <Button
              color="red"
              loading={reset.isPending}
              disabled={!target || (!!config?.demoCodeRequired && !code)}
              onClick={() => {
                if (target) reset.mutate(target);
              }}
            >
              {t.confirm}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
