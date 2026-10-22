import { useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetApplicationQueryKey,
  getListApplicationConsentsQueryKey,
  useRequestConsentSigning,
  type listApplicationConsentsResponse,
} from '@/api/generated/api';
import type {
  ConsentItemOut,
  ConsentRef,
  ConsentsOut,
  ConsentsSignedOut,
  SignChallenge,
} from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatDate, formatDateTime } from '@/lib/format';
import { consents as t, fill } from '@/texts';
import { ConsentCodeForm } from './ConsentCodeForm';
import { useConsents } from './useConsents';

function keyOf(item: Pick<ConsentItemOut, 'kind' | 'subjectInn'>): string {
  return `${item.subjectInn}:${item.kind}`;
}

function knownKind(kind: string): kind is keyof typeof t.kind {
  return Object.hasOwn(t.kind, kind);
}

/** Текст доступен до подписи, но открывать его для подтверждения необязательно (D-092). */
function DocumentText({ title, version, text }: { title: string; version: string; text: string }) {
  return (
    <details>
      <summary>{title}</summary>
      <Text size="xs" c="dimmed" mt="xs">
        {fill(t.version, { version })}
      </Text>
      <Text size="sm" mt="xs" style={{ whiteSpace: 'pre-wrap' }}>
        {text}
      </Text>
    </details>
  );
}

function ConsentList({
  view,
  chosen,
  locked,
  onToggle,
}: {
  view: ConsentsOut;
  chosen: Set<string>;
  locked: boolean;
  onToggle: (item: ConsentItemOut, checked: boolean) => void;
}) {
  const subjects = [...new Set(view.items.map((item) => item.subjectInn))];
  return (
    <Stack gap="md">
      {subjects.map((inn) => {
        const items = view.items.filter((item) => item.subjectInn === inn);
        return (
          <Paper
            component="section"
            aria-labelledby={`consent-subject-${inn}`}
            key={inn}
            withBorder
            p="md"
          >
            <Stack gap="md">
              <Title order={3} size="h4" id={`consent-subject-${inn}`}>
                {items[0]?.subjectName}
              </Title>
              {items.map((item) => {
                const kind = item.kind;
                const known = knownKind(kind);
                const title = known ? t.kind[kind] : kind;
                const signed = item.status === 'SIGNED';
                return (
                  <Stack key={keyOf(item)} gap="xs">
                    {signed ? (
                      <Group>
                        <Text fw={500}>{title}</Text>
                        <Badge color="green">
                          {fill(t.signed, { date: formatDateTime(item.signedAt) })}
                        </Badge>
                      </Group>
                    ) : (
                      <Checkbox
                        label={fill(t.agree, { kind: title })}
                        description={known ? t.why[kind] : undefined}
                        checked={chosen.has(keyOf(item))}
                        disabled={locked || !item.canSign || !known}
                        onChange={(event) => onToggle(item, event.currentTarget.checked)}
                      />
                    )}
                    {item.status === 'EXPIRED' ? (
                      <Text size="sm" c="orange.9">
                        {t.expired}
                      </Text>
                    ) : null}
                    {!signed && !item.canSign ? (
                      <Text size="sm" c="dimmed">
                        {t.noPermission}
                      </Text>
                    ) : null}
                    {signed && item.validUntil ? (
                      <Text size="sm" c="dimmed">
                        {fill(t.validUntil, { date: formatDate(item.validUntil) })}
                      </Text>
                    ) : null}
                    <DocumentText title={t.text} version={item.textVersion} text={item.text} />
                  </Stack>
                );
              })}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}

export function ConsentsStep({ applicationId }: { applicationId: string }) {
  const query = useConsents(applicationId);
  const client = useQueryClient();
  const request = useRequestConsentSigning<unknown>();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set());
  const [pepAccepted, setPepAccepted] = useState(false);
  const [challenge, setChallenge] = useState<{ value: SignChallenge; issuedAt: number } | null>(
    null,
  );
  const busy = useRef(false);
  const view = query.data;
  const available =
    view?.items.filter(
      (item) => item.status !== 'SIGNED' && item.canSign && knownKind(item.kind),
    ) ?? [];
  const selected: ConsentRef[] = available
    .filter((item) => chosen.has(keyOf(item)))
    .map((item) => ({ kind: item.kind as ConsentRef['kind'], subjectInn: item.subjectInn }));
  const canRequest =
    selected.length > 0 && (view?.pepRules.accepted || pepAccepted) && !request.isPending;

  const requestCode = async (items = selected) => {
    if (busy.current || !view || items.length === 0) return;
    busy.current = true;
    try {
      const response = await request.mutateAsync({
        applicationId,
        data: { items, acceptPepRules: view.pepRules.accepted || pepAccepted },
      });
      if (response.status === 200) setChallenge({ value: response.data, issuedAt: Date.now() });
    } catch {
      // Ошибка запроса показана рядом с кнопкой; галочки остаются выбранными.
    } finally {
      busy.current = false;
    }
  };

  const onSigned = (result: ConsentsSignedOut) => {
    client.setQueryData<listApplicationConsentsResponse>(
      getListApplicationConsentsQueryKey(applicationId),
      (old) =>
        old?.status === 200
          ? {
              ...old,
              data: {
                ...old.data,
                allSigned: result.allSigned,
                pepRules: { ...old.data.pepRules, accepted: true },
                items: old.data.items.map(
                  (item) => result.signed.find((signed) => keyOf(signed) === keyOf(item)) ?? item,
                ),
              },
            }
          : old,
    );
    setChosen(new Set());
    setChallenge(null);
    request.reset();
    void client.invalidateQueries({ queryKey: getListApplicationConsentsQueryKey(applicationId) });
    void client.invalidateQueries({ queryKey: getGetApplicationQueryKey(applicationId) });
  };

  if (!view) {
    return query.isPending ? (
      <Group role="status">
        <Loader size="sm" />
        <Text>{t.loading}</Text>
      </Group>
    ) : (
      <ProblemAlert
        error={query.error}
        onAction={() => {
          void query.refetch();
        }}
      />
    );
  }
  const subjects = [...new Set(view.items.map((item) => item.subjectInn))];
  const signedSubjects = subjects.filter((inn) =>
    view.items.filter((item) => item.subjectInn === inn).every((item) => item.status === 'SIGNED'),
  );
  const waiting = [
    ...new Set(
      view.items.filter((item) => item.status !== 'SIGNED').map((item) => item.subjectName),
    ),
  ];

  return (
    <Stack gap="md" maw={720}>
      <Title order={2} size="h3">
        {t.heading}
      </Title>
      <Text c="dimmed">{t.hint}</Text>
      <Text role="status">
        {fill(t.progress, { signed: signedSubjects.length, total: subjects.length })}
      </Text>
      {view.allSigned ? (
        <Alert color="green">{t.allSigned}</Alert>
      ) : (
        <Text size="sm">{fill(t.waiting, { names: waiting.join(', ') })}</Text>
      )}
      {query.isError ? (
        <ProblemAlert
          error={query.error}
          onAction={() => {
            void query.refetch();
          }}
        />
      ) : null}
      <ConsentList
        view={view}
        chosen={chosen}
        locked={challenge !== null || request.isPending}
        onToggle={(item, checked) =>
          setChosen((old) => {
            const next = new Set(old);
            if (checked) next.add(keyOf(item));
            else next.delete(keyOf(item));
            return next;
          })
        }
      />
      {!view.allSigned && available.length > 0 ? (
        <>
          <DocumentText
            title={t.pepHeading}
            version={view.pepRules.version}
            text={view.pepRules.text}
          />
          {view.pepRules.accepted ? (
            <Text size="sm">{t.pepAccepted}</Text>
          ) : (
            <Checkbox
              label={t.pepAccept}
              checked={pepAccepted}
              disabled={challenge !== null || request.isPending}
              onChange={(event) => setPepAccepted(event.currentTarget.checked)}
            />
          )}
          {challenge ? (
            <ConsentCodeForm
              key={challenge.value.requestId}
              applicationId={applicationId}
              challenge={challenge.value}
              issuedAt={challenge.issuedAt}
              requesting={request.isPending}
              requestError={request.error}
              onSigned={onSigned}
              onNewCode={() => {
                void requestCode(challenge.value.items);
              }}
              onChangeBundle={() => {
                setChallenge(null);
                request.reset();
                void query.refetch();
              }}
            />
          ) : (
            <>
              {request.error ? <ProblemAlert error={request.error} /> : null}
              <div>
                <Button
                  disabled={!canRequest}
                  loading={request.isPending}
                  onClick={() => {
                    void requestCode();
                  }}
                >
                  {t.requestCode}
                </Button>
              </div>
              {!canRequest ? (
                <Text size="sm" c="dimmed">
                  {t.selectHint}
                </Text>
              ) : null}
            </>
          )}
        </>
      ) : !view.allSigned ? (
        <Alert color="gray">{t.noAvailable}</Alert>
      ) : null}
    </Stack>
  );
}
