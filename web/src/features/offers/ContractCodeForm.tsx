import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, Stack, Text, TextInput } from '@mantine/core';
import { useSignContract } from '@/api/generated/api';
import type { ContractOut, SignChallengeOut } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { fill } from '@/texts';
import { contractTexts as t } from '@/texts/contract';

export function ContractCodeForm({
  contractId,
  challenge,
  issuedAt,
  onSigned,
  onNewCode,
  requesting,
}: {
  contractId: string;
  challenge: SignChallengeOut;
  issuedAt: number;
  onSigned: (contract: ContractOut) => void;
  onNewCode: () => void;
  requesting: boolean;
}) {
  const action = useActionKey();
  const sign = useSignContract<unknown>({ request: action.request() });
  const [code, setCode] = useState('');
  const [attempts, setAttempts] = useState(3);
  const [now, setNow] = useState(Date.now);
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
      const result = await sign.mutateAsync({
        contractId,
        data: { requestId: challenge.requestId, code },
      });
      if (result.status === 200) onSigned(result.data.contract);
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
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      {challenge.demoCode ? (
        <Alert color="gray">
          <Text fw={700}>{fill(t.demoCode, { code: challenge.demoCode })}</Text>
          <Text size="sm">{t.demoHint}</Text>
        </Alert>
      ) : null}
      <TextInput
        ref={input}
        label={t.code}
        value={code}
        required
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        disabled={dead || requesting}
        onChange={(event) => setCode(event.currentTarget.value.replace(/\D/g, '').slice(0, 6))}
      />
      {blocked ? (
        <Alert color="red" role="alert">
          {t.blocked}
        </Alert>
      ) : null}
      {expired && !blocked ? (
        <Alert color="yellow" role="alert">
          {t.expired}
        </Alert>
      ) : null}
      {!dead && errorCode === 'CODE_INVALID' ? (
        <Alert color="red" role="alert">
          {fill(t.wrong, { attempts })}
        </Alert>
      ) : null}
      {sign.error &&
      !['CODE_INVALID', 'CODE_ATTEMPTS_EXCEEDED', 'CODE_EXPIRED'].includes(errorCode ?? '') ? (
        <ProblemAlert error={sign.error} />
      ) : null}
      {!dead ? (
        <Group>
          <Text size="sm" role="timer">
            {fill(t.expires, { seconds })}
          </Text>
          <Text size="sm">{fill(t.attempts, { attempts })}</Text>
        </Group>
      ) : null}
      <div>
        {dead ? (
          <Button type="button" loading={requesting} onClick={onNewCode}>
            {t.newCode}
          </Button>
        ) : (
          <Button type="submit" loading={sign.isPending} disabled={!ready}>
            {t.sign}
          </Button>
        )}
      </div>
    </Stack>
  );
}
