import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { useSignConsentBundle } from '@/api/generated/api';
import type { ConsentsSignedOut, SignChallenge } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { ProblemAlert } from '@/components/ProblemAlert';
import { consents as t, fill } from '@/texts';

/** Код привязан к неизменному набору challenge.items, а не текущим галочкам. */
export function ConsentCodeForm({
  applicationId,
  challenge,
  issuedAt,
  onSigned,
  onNewCode,
  onChangeBundle,
  requesting,
  requestError,
}: {
  applicationId: string;
  challenge: SignChallenge;
  issuedAt: number;
  onSigned: (result: ConsentsSignedOut) => void;
  onNewCode: () => void;
  onChangeBundle: () => void;
  requesting: boolean;
  requestError: unknown;
}) {
  const sign = useSignConsentBundle<unknown>();
  const [code, setCode] = useState('');
  const [attempts, setAttempts] = useState(3);
  const [now, setNow] = useState(() => Date.now());
  const input = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  useEffect(() => {
    input.current?.focus();
    const interval = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(interval);
  }, []);
  const seconds = Math.max(
    0,
    Math.ceil((issuedAt + challenge.expiresInSeconds * 1_000 - now) / 1_000),
  );
  const errorCode = isAppError(sign.error) ? sign.error.code : null;
  const blocked = attempts === 0 || errorCode === 'CODE_ATTEMPTS_EXCEEDED';
  const expired = seconds === 0 || errorCode === 'CODE_EXPIRED';
  const dead = blocked || expired;
  const ready = /^\d{6}$/.test(code) && !dead && !sign.isPending && !requesting;

  const submit = async () => {
    if (!ready || busy.current) return;
    busy.current = true;
    try {
      const response = await sign.mutateAsync({
        applicationId,
        data: { requestId: challenge.requestId, code, items: challenge.items },
      });
      if (response.status === 200) onSigned(response.data);
    } catch (error) {
      if (isAppError(error) && error.code === 'CODE_INVALID') {
        setAttempts((left) => Math.max(0, left - 1));
        setCode('');
        input.current?.focus();
      }
    } finally {
      busy.current = false;
    }
  };

  return (
    <Stack
      component="form"
      gap="md"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <Title order={3} size="h4">
        {t.codeHeading}
      </Title>
      <Text size="sm">{t.bundle}</Text>
      {challenge.demoCode ? (
        <Alert color="gray" data-testid="consent-demo-code">
          <Text fw={700}>{fill(t.demoCode, { code: challenge.demoCode })}</Text>
          <Text size="sm">{t.demoHint}</Text>
        </Alert>
      ) : null}
      <TextInput
        ref={input}
        label={t.codeLabel}
        value={code}
        required
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        disabled={dead || requesting}
        error={errorCode === 'CODE_INVALID' || undefined}
        onChange={(event) => setCode(event.currentTarget.value.replace(/\D/g, '').slice(0, 6))}
      />
      {blocked ? (
        <Alert color="red" role="alert">
          {t.blocked}
        </Alert>
      ) : null}
      {expired && !blocked ? (
        <Alert color="yellow" role="alert">
          {t.expiredCode}
        </Alert>
      ) : null}
      {!dead && errorCode === 'CODE_INVALID' ? (
        <Alert color="red" role="alert">
          {fill(t.wrongCode, { attempts })}
        </Alert>
      ) : null}
      {sign.error &&
      !['CODE_INVALID', 'CODE_EXPIRED', 'CODE_ATTEMPTS_EXCEEDED'].includes(errorCode ?? '') ? (
        <ProblemAlert error={sign.error} />
      ) : null}
      {requestError ? <ProblemAlert error={requestError} /> : null}
      {!dead ? (
        <Group>
          <Text size="sm" c="dimmed" role="timer">
            {fill(t.expires, { seconds })}
          </Text>
          <Text size="sm" c="dimmed">
            {fill(t.attempts, { attempts })}
          </Text>
        </Group>
      ) : null}
      <Group>
        <Button
          variant="default"
          type="button"
          onClick={onChangeBundle}
          disabled={sign.isPending || requesting}
        >
          {t.changeBundle}
        </Button>
        {dead ? (
          <Button type="button" onClick={onNewCode} loading={requesting}>
            {t.newCode}
          </Button>
        ) : (
          <Button type="submit" loading={sign.isPending} disabled={!ready}>
            {t.sign}
          </Button>
        )}
      </Group>
    </Stack>
  );
}
