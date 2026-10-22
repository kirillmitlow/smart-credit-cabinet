import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, Stack, Text, TextInput, Title } from '@mantine/core';
import { useVerifyLoginCode } from '@/api/generated/api';
import type { CodeIssued, MeResponse } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { ProblemAlert } from '@/components/ProblemAlert';
import { errorTexts, fill, login, otherErrors } from '@/texts';
import type { LoginChoice } from './WhoStep';
import { useFocusOnMount } from './useFocusOnMount';

const t = login.codeStep;
const MAX_ATTEMPTS = 3;
const CODE_LENGTH = 6;

function clock(totalSeconds: number): string {
  const safe = Math.max(0, totalSeconds);
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/** Сколько секунд осталось до конца жизни кода; обновляется раз в секунду */
function useSecondsLeft(issuedAt: number, expiresInSeconds: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return Math.max(0, Math.ceil((issuedAt + expiresInSeconds * 1000 - now) / 1000));
}

/**
 * Шаги 3–4 входа (60-03 №1): в демо код показан плашкой на экране, поле на 6 цифр, остаток попыток
 * и время жизни. Ошибки: неверный код (остаток), истёк или попытки кончились («Получить новый»).
 */
export function CodeStep({
  choice,
  issued,
  issuedAt,
  requestingNew,
  newCodeError,
  onNewCode,
  onBack,
  onLoggedIn,
}: {
  choice: LoginChoice;
  issued: CodeIssued;
  issuedAt: number;
  requestingNew: boolean;
  newCodeError: unknown;
  onNewCode: () => void;
  onBack: () => void;
  onLoggedIn: (me: MeResponse) => void;
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const inputRef = useRef<HTMLInputElement>(null);
  const verify = useVerifyLoginCode();
  const [code, setCode] = useState('');
  const [attemptsLeft, setAttemptsLeft] = useState(MAX_ATTEMPTS);
  const [wrongCode, setWrongCode] = useState(false);
  const secondsLeft = useSecondsLeft(issuedAt, issued.expiresInSeconds);

  const expired = secondsLeft <= 0;
  const error = verify.error;
  const errorCode = isAppError(error) ? error.code : null;
  const exhausted = attemptsLeft <= 0 || errorCode === 'CODE_ATTEMPTS_EXCEEDED';
  const dead = expired || exhausted || errorCode === 'CODE_EXPIRED';
  const ready = code.length === CODE_LENGTH && !dead && !verify.isPending;

  const submit = () => {
    if (!ready) return;
    setWrongCode(false);
    verify.mutate(
      { data: { requestId: issued.requestId, code } },
      {
        onSuccess: (response) => {
          if (response.status === 200) onLoggedIn(response.data);
        },
        onError: (failure) => {
          if (isAppError(failure) && failure.code === 'CODE_INVALID') {
            setAttemptsLeft((left) => Math.max(0, left - 1));
            setWrongCode(true);
            setCode('');
            inputRef.current?.focus({ preventScroll: true });
          }
        },
      },
    );
  };

  const who = choice.companyName
    ? fill(t.signingAsCompany, { name: choice.userName, company: choice.companyName })
    : fill(t.signingAs, { name: choice.userName });

  return (
    <Stack
      component="form"
      gap="md"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Title order={2} size="h3" ref={headingRef} tabIndex={-1}>
        {t.heading}
      </Title>
      <Text>{who}</Text>

      {issued.demoCode ? (
        <Alert color="gray" variant="light" data-testid="demo-code">
          <Text fw={700} size="lg">
            {fill(t.demoCode, { code: issued.demoCode })}
          </Text>
          <Text size="sm">{t.demoBanner}</Text>
        </Alert>
      ) : null}

      <TextInput
        ref={inputRef}
        label={t.label}
        value={code}
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={CODE_LENGTH}
        required
        disabled={dead}
        error={wrongCode || undefined}
        onChange={(event) =>
          setCode(event.currentTarget.value.replace(/\D/g, '').slice(0, CODE_LENGTH))
        }
      />

      {wrongCode && !exhausted ? (
        <Alert color="red" variant="light" role="alert">
          {fill(otherErrors.wrongLoginCode, { attempts: attemptsLeft })}
        </Alert>
      ) : null}
      {error && errorCode !== 'CODE_INVALID' ? (
        <ProblemAlert error={error} onAction={onNewCode} />
      ) : null}
      {wrongCode && exhausted && errorCode === 'CODE_INVALID' ? (
        <Alert color="red" variant="light" role="alert">
          {errorTexts.CODE_ATTEMPTS_EXCEEDED.text}
        </Alert>
      ) : null}
      {expired && errorCode !== 'CODE_EXPIRED' && !exhausted ? (
        <Alert color="yellow" variant="light" role="alert">
          {t.expired}
        </Alert>
      ) : null}
      {newCodeError ? <ProblemAlert error={newCodeError} /> : null}

      <Group gap="md">
        {dead ? null : (
          <>
            <Text size="sm" c="dimmed" role="timer">
              {fill(t.timeLeft, { time: clock(secondsLeft) })}
            </Text>
            <Text size="sm" c="dimmed">
              {fill(t.attemptsLeft, { attempts: attemptsLeft })}
            </Text>
          </>
        )}
      </Group>

      <Group>
        <Button variant="default" type="button" onClick={onBack}>
          {t.back}
        </Button>
        {dead ? (
          <Button type="button" onClick={onNewCode} loading={requestingNew}>
            {t.newCode}
          </Button>
        ) : (
          <Button type="submit" disabled={!ready} loading={verify.isPending}>
            {t.submit}
          </Button>
        )}
      </Group>
    </Stack>
  );
}
