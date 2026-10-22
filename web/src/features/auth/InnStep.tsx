import { useState } from 'react';
import { Anchor, Button, Stack, Text, TextInput, Title } from '@mantine/core';
import { Link } from 'react-router';
import { ProblemAlert } from '@/components/ProblemAlert';
import { innProblem, normalizeInn } from '@/lib/inn';
import { errorTexts, fill, login } from '@/texts';
import { useFocusOnMount } from './useFocusOnMount';

const t = login.innStep;

/** Шаг 1: ИНН. Длину и контрольную сумму проверяем на лету, до обращения к серверу */
export function InnStep({
  initialInn,
  serverError,
  showUnderwriter,
  onSubmit,
}: {
  initialInn: string;
  /** Сервер не принял ИНН (не найден, неверный): показываем под полем, пока человек не правит номер */
  serverError?: unknown;
  showUnderwriter: boolean;
  onSubmit: (inn: string) => void;
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [value, setValue] = useState(initialInn);
  const [touched, setTouched] = useState(false);
  const [serverErrorVisible, setServerErrorVisible] = useState(true);

  const problem = innProblem(value);
  // Ошибку длины не показываем, пока человек печатает: только после ухода из поля или нажатия кнопки.
  // Опечатку в контрольной сумме видно сразу, когда цифр уже достаточно.
  const message =
    problem === 'checksum'
      ? t.checksum
      : problem === 'length' && touched
        ? errorTexts.INN_INVALID.text
        : null;

  return (
    <Stack
      component="form"
      gap="md"
      {...{ noValidate: true }}
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        setServerErrorVisible(false);
        if (problem === null) onSubmit(value);
      }}
    >
      <Title order={2} size="h3" ref={headingRef} tabIndex={-1}>
        {t.heading}
      </Title>
      <TextInput
        label={t.label}
        description={t.hint}
        value={value}
        inputMode="numeric"
        autoComplete="off"
        required
        error={message}
        onChange={(event) => {
          setValue(normalizeInn(event.currentTarget.value));
          setServerErrorVisible(false);
        }}
        onBlur={() => setTouched(true)}
        rightSectionWidth="auto"
        rightSection={
          value.length > 0 && problem === 'length' ? (
            <Text size="xs" c="dimmed" pr="xs">
              {fill(t.lengthCounter, { count: value.length })}
            </Text>
          ) : null
        }
      />
      {serverError && serverErrorVisible ? <ProblemAlert error={serverError} /> : null}
      <Button type="submit">{t.submit}</Button>
      {showUnderwriter ? (
        <Anchor component={Link} to="/login?zone=bank" size="xs">
          {t.underwriter}
        </Anchor>
      ) : null}
    </Stack>
  );
}
