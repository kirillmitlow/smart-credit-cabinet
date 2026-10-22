import { useState } from 'react';
import { Alert, Button, Card, Group, Radio, Stack, Text, Title } from '@mantine/core';
import type { CompanyBrief, RolesResponse } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { fill, login } from '@/texts';
import { companyStatusText, roleText } from './labels';
import { useFocusOnMount } from './useFocusOnMount';

const t = login.whoStep;

/** Кому и от чьего имени выпускаем код: человек и (если нужно) компания */
export interface LoginChoice {
  userId: string;
  userName: string;
  companyId: string | null;
  companyName: string | null;
}

/**
 * Шаг 2 (60-03 №1): 2а — карточка компании и список людей; 2б — личный ИНН: «Вы руководитель…»
 * или выбор из нескольких компаний. Кнопка «Получить код» создаёт код для выбранного человека.
 */
export function WhoStep({
  roles,
  pending,
  error,
  onSubmit,
  onBack,
}: {
  roles: RolesResponse;
  pending: boolean;
  error: unknown;
  onSubmit: (choice: LoginChoice) => void;
  onBack: () => void;
}) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const people = roles.people ?? [];
  const companies = roles.companies ?? [];
  const isCompany = roles.kind === 'COMPANY';

  const [userId, setUserId] = useState<string>(
    people.length === 1 ? (people[0]?.userId ?? '') : '',
  );
  const [companyId, setCompanyId] = useState<string>(companies[0]?.company.id ?? '');

  const chosenCompany: CompanyBrief | null = isCompany
    ? (roles.company ?? null)
    : (companies.find((item) => item.company.id === companyId)?.company ?? null);
  const person = people.find((item) => item.userId === userId) ?? null;
  const nobodyToLogin = isCompany && people.length === 0;

  const submit = () => {
    const user = isCompany ? person : (people[0] ?? null);
    if (!user) return;
    onSubmit({
      userId: user.userId,
      userName: user.displayName,
      companyId: chosenCompany?.id ?? null,
      companyName: chosenCompany?.name ?? null,
    });
  };

  const canSubmit = !pending && (isCompany ? person !== null : chosenCompany !== null);

  return (
    <Stack
      component="form"
      gap="md"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) submit();
      }}
    >
      <Title order={2} size="h3" ref={headingRef} tabIndex={-1}>
        {t.heading}
      </Title>

      {isCompany && roles.company ? (
        <Card withBorder padding="md" data-testid="company-card">
          <Text fw={600}>
            {fill(t.companyLine, {
              name: roles.company.name,
              status: companyStatusText(roles.company.status),
            })}
          </Text>
        </Card>
      ) : null}

      {chosenCompany && !chosenCompany.canApply ? (
        <Alert color="yellow" role="status">
          {t.notActive}
        </Alert>
      ) : null}

      {isCompany ? (
        nobodyToLogin ? (
          <Text>{t.noPeople}</Text>
        ) : (
          <Radio.Group label={t.chooseUser} value={userId} onChange={setUserId} required>
            <Stack gap="xs" mt="xs">
              {people.map((item) => (
                <Radio
                  key={item.userId}
                  value={item.userId}
                  label={fill(t.userOption, {
                    name: item.displayName,
                    role: roleText(item.role),
                  })}
                />
              ))}
            </Stack>
          </Radio.Group>
        )
      ) : (
        <Stack gap="sm">
          {companies.length === 1 && chosenCompany ? (
            <Text>
              {fill(t.personOne, {
                company: chosenCompany.name,
                role: roleText(companies[0]?.role ?? ''),
              })}
            </Text>
          ) : (
            <Text>{t.personMany}</Text>
          )}
          <Radio.Group
            label={companies.length === 1 ? t.chooseCompanyOne : t.chooseCompanyMany}
            value={companyId}
            onChange={setCompanyId}
            required
          >
            <Stack gap="xs" mt="xs">
              {companies.map((item) => (
                <Radio
                  key={item.company.id}
                  value={item.company.id}
                  label={fill(t.companyOption, {
                    name: item.company.name,
                    role: roleText(item.role),
                  })}
                />
              ))}
            </Stack>
          </Radio.Group>
        </Stack>
      )}

      {error ? <ProblemAlert error={error} /> : null}

      <Group>
        <Button variant="default" type="button" onClick={onBack}>
          {t.back}
        </Button>
        <Button type="submit" disabled={!canSubmit} loading={pending}>
          {t.submit}
        </Button>
      </Group>
    </Stack>
  );
}
