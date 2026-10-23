import { useState } from 'react';
import { Button, Group, NumberInput, Paper, Select, Stack, Text, Title } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { demoSetChaos } from '@/api/generated/api';
import type { ChaosView, ChaosInputMode } from '@/api/generated/model';
import { appErrorFromResponse } from '@/api/errors';
import { ProblemAlert } from '@/components/ProblemAlert';
import { usePublicConfig } from '@/features/auth/session';
import { demo as t } from '@/texts/demo';
import { chaosKey, useChaos } from './api';

function Control({ item, code }: { item: ChaosView; code: string }) {
  const [mode, setMode] = useState<ChaosInputMode>('OK');
  const [latency, setLatency] = useState<string | number>(5000);
  const cache = useQueryClient();
  const cloud = usePublicConfig().data?.demoCodeRequired;
  const change = useMutation({
    mutationFn: async () => {
      const r = await demoSetChaos(
        item.system,
        { mode, latencyMs: mode === 'SLOW' ? Number(latency) : null },
        { headers: { 'X-Demo-Code': code } },
      );
      if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
      return r.data;
    },
    onSuccess: () => void cache.invalidateQueries({ queryKey: chaosKey }),
  });
  return (
    <Paper withBorder p="md">
      <Stack gap="xs">
        <Title order={3} size="h4">
          {t.systems[item.system]}
        </Title>
        <Text>
          {item.available
            ? (t.modes[item.mode as keyof typeof t.modes] ?? item.mode)
            : t.unavailable}
        </Text>
        <Select
          label={`${t.chooseMode}: ${t.systems[item.system]}`}
          data={Object.entries(t.modes).map(([value, label]) => ({ value, label }))}
          value={mode}
          onChange={(v) => {
            if (v) setMode(v as ChaosInputMode);
          }}
          allowDeselect={false}
        />
        {mode === 'SLOW' ? (
          <NumberInput
            label={t.ms}
            value={latency}
            onChange={setLatency}
            min={0}
            max={120000}
            allowDecimal={false}
          />
        ) : null}
        {change.isError ? <ProblemAlert error={change.error} /> : null}
        {change.isSuccess ? <Text role="status">{t.queued}</Text> : null}
        <Group>
          <Button
            variant="light"
            loading={change.isPending}
            disabled={!!cloud && !code}
            onClick={() => change.mutate()}
          >
            {t.set}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
export function DemoChaos({ code }: { code: string }) {
  const query = useChaos();
  return (
    <Stack>
      <Title order={2}>{t.chaos}</Title>
      <Text>{t.chaosHelp}</Text>
      {query.isError ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {query.data?.map((item) => (
        <Control key={item.system} item={item} code={code} />
      ))}
    </Stack>
  );
}
