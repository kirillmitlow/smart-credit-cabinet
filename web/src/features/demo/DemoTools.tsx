import { useState } from 'react';
import { Accordion, Alert, Anchor, Box, Button, Drawer, Group, Stack, Text } from '@mantine/core';
import { Link, useLocation } from 'react-router';
import { useGetApplication } from '@/api/generated/api';
import { appErrorFromResponse } from '@/api/errors';
import { useSession } from '@/features/auth/session';
import { demo as t } from '@/texts/demo';
import { useChaos, usePersonas } from './api';
import { DemoPanel } from './DemoPanel';
import { outcome } from './formatting';

function ExpectedHint({ id }: { id: string }) {
  const session = useSession('client');
  const personas = usePersonas(!!session.data);
  const application = useGetApplication(id, {
    query: {
      enabled: !!session.data,
      select: (r) => {
        if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
        return r.data;
      },
    },
  });
  const a = application.data;
  const p = personas.data?.find(
    (p) =>
      p.companyId === a?.companyId &&
      !!p.application &&
      p.application.productCode === a?.productCode &&
      Number(p.application.amountRub) === a?.amountRub &&
      p.application.termMonths === a?.termMonths,
  );
  if (!p) return null;
  return (
    <Box px="md" pb="xs" data-testid="demo-expected-hint">
      <Accordion>
        <Accordion.Item value={id}>
          <Accordion.Control>{t.hint}</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <Text size="sm">{t.hintHelp}</Text>
              <Text>
                {p.title}: {outcome(p.expectedOutcome)}
              </Text>
              {p.expectedFinalOutcome ? (
                <Text>
                  {t.final}: {outcome(p.expectedFinalOutcome)}
                </Text>
              ) : null}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Box>
  );
}

/** Корневой демо-инструмент, без правок клиентских экранов зоны A. */
export default function DemoTools() {
  const [opened, setOpened] = useState(false);
  const location = useLocation();
  const chaos = useChaos();
  const active = chaos.data?.filter((c) => !c.available || c.mode !== 'OK') ?? [];
  const match = /^\/applications\/([^/]+)$/.exec(location.pathname);
  return (
    <>
      {active.length ? (
        <Alert color="red" role="status" title={t.active}>
          {active
            .map(
              (c) =>
                `${t.systems[c.system]}: ${c.available ? (t.modes[c.mode as keyof typeof t.modes] ?? c.mode) : t.unavailable}`,
            )
            .join(' · ')}
        </Alert>
      ) : null}
      {location.pathname !== '/demo' ? (
        <Group justify="flex-end" px="md" py={4}>
          <Button variant="subtle" size="compact-sm" onClick={() => setOpened(true)}>
            {t.open}
          </Button>
        </Group>
      ) : null}
      {match?.[1] ? <ExpectedHint key={match[1]} id={match[1]} /> : null}
      <Drawer
        opened={opened}
        onClose={() => setOpened(false)}
        title={t.title}
        closeButtonProps={{ 'aria-label': t.close }}
        position="right"
        size="lg"
      >
        {opened ? (
          <Stack>
            <Anchor component={Link} to="/demo" onClick={() => setOpened(false)}>
              {t.full}
            </Anchor>
            <DemoPanel onResetAll={() => setOpened(false)} />
          </Stack>
        ) : null}
      </Drawer>
    </>
  );
}
