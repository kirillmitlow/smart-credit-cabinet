import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import {
  getGetContractQueryKey,
  getGetContractDocumentUrl,
  useGetApplicationOffer,
  useGetContract,
  useListApplicationConsents,
  useRequestContractSignature,
  useRequestContractSigningCode,
  type getContractResponse,
} from '@/api/generated/api';
import type { ContractOut, SignChallengeOut } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { resolveUrl } from '@/api/client';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { fill } from '@/texts';
import { contractTexts as t } from '@/texts/contract';
import { updateApplicationStatus } from './cache';
import { ContractCodeForm } from './ContractCodeForm';

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between">
      <Text c="dimmed">{label}</Text>
      <Text fw={600}>{value}</Text>
    </Group>
  );
}

function SigningForm({
  contract,
  onSigned,
  refresh,
}: {
  contract: ContractOut;
  onSigned: (next: ContractOut) => void;
  refresh: () => void;
}) {
  const [agree, setAgree] = useState(false);
  const [pepAccepted, setPepAccepted] = useState(false);
  const [challenge, setChallenge] = useState<{ value: SignChallengeOut; issuedAt: number } | null>(
    null,
  );
  const action = useActionKey();
  const request = useRequestContractSigningCode<unknown>({ request: action.request() });
  const busy = useRef(false);
  const consents = useListApplicationConsents(contract.applicationId, {
    query: { select: (result) => (result.status === 200 ? result.data : undefined) },
  });
  const pep = consents.data?.pepRules;
  const ready = agree && pep !== undefined && (pep.accepted || pepAccepted);
  const requestCode = async () => {
    if (!ready || busy.current) return;
    busy.current = true;
    try {
      const response = await request.mutateAsync({
        contractId: contract.id,
        data: { agree, acceptPepRules: pep.accepted || pepAccepted },
      });
      if (response.status === 200) {
        action.reset();
        setChallenge({ value: response.data, issuedAt: Date.now() });
      }
    } catch (error) {
      if (isAppError(error) && error.code === 'ROLE_CANNOT_SIGN') refresh();
    } finally {
      busy.current = false;
    }
  };

  return (
    <Stack gap="md">
      <Checkbox
        label={t.agree}
        checked={agree}
        disabled={challenge !== null || request.isPending}
        onChange={(event) => setAgree(event.currentTarget.checked)}
      />
      {consents.isError ? (
        <ProblemAlert error={consents.error} onAction={() => void consents.refetch()} />
      ) : null}
      {pep && !pep.accepted ? (
        <>
          <details>
            <summary>{t.pep}</summary>
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
              {pep.text}
            </Text>
          </details>
          <Checkbox
            label={t.acceptPep}
            checked={pepAccepted}
            disabled={challenge !== null || request.isPending}
            onChange={(event) => setPepAccepted(event.currentTarget.checked)}
          />
        </>
      ) : null}
      {request.error ? <ProblemAlert error={request.error} /> : null}
      {challenge ? (
        <ContractCodeForm
          key={challenge.value.requestId}
          contractId={contract.id}
          challenge={challenge.value}
          issuedAt={challenge.issuedAt}
          onSigned={onSigned}
          onNewCode={() => void requestCode()}
          requesting={request.isPending}
        />
      ) : (
        <div>
          <Button disabled={!ready} loading={request.isPending} onClick={() => void requestCode()}>
            {t.requestCode}
          </Button>
        </div>
      )}
    </Stack>
  );
}

function ContractView({
  contractId,
  applicationId,
}: {
  contractId: string;
  applicationId: string;
}) {
  const client = useQueryClient();
  const query = useGetContract(contractId, {
    query: {
      select: (result) => (result.status === 200 ? result.data : undefined),
      refetchInterval: (state) =>
        state.state.data?.status === 200 && state.state.data.data.applicationStatus === 'DISBURSED'
          ? false
          : 3_000,
    },
  });
  const contract = query.data;
  const passKey = useActionKey();
  const pass = useRequestContractSignature<unknown>({ request: passKey.request() });
  const passBusy = useRef(false);
  const [passed, setPassed] = useState(false);
  const status = contract?.applicationStatus;
  useEffect(() => {
    if (status) updateApplicationStatus(client, applicationId, status);
  }, [client, applicationId, status]);

  const onSigned = (next: ContractOut) => {
    client.setQueryData<getContractResponse>(getGetContractQueryKey(contractId), {
      data: next,
      status: 200,
      headers: new Headers(),
    });
    updateApplicationStatus(client, applicationId, next.applicationStatus);
  };
  const passToDirector = async () => {
    if (passBusy.current || passed) return;
    passBusy.current = true;
    try {
      const result = await pass.mutateAsync({ contractId });
      if (result.status === 200) {
        setPassed(true);
        passKey.reset();
      }
    } catch {
      // Ошибка рядом с действием; повтор сохраняет ключ.
    } finally {
      passBusy.current = false;
    }
  };

  if (!contract)
    return query.isPending ? (
      <Group role="status">
        <Loader size="sm" />
        <Text>{t.loading}</Text>
      </Group>
    ) : (
      <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
    );
  const signed = contract.status === 'SIGNED';
  const isLimit = contract.productCode === 'CREDIT_LINE' || contract.productCode === 'OVERDRAFT';
  const delivery =
    status === 'DISBURSED' ? t.issued : status === 'DISBURSING' ? t.issuing : t.signedNotice;
  return (
    <Stack gap="md" maw={720}>
      <Title order={2} size="h3">
        {signed ? t.signedHeading : t.heading}
      </Title>
      <Text fw={600}>{fill(t.number, { number: contract.number })}</Text>
      <Fact label={isLimit ? t.limit : t.amount} value={formatMoney(contract.amountRub)} />
      <Fact label={t.term} value={formatTermMonths(contract.termMonths)} />
      <Fact label={t.rate} value={formatPercent(contract.ratePercent)} />
      {!isLimit ? <Fact label={t.payment} value={formatMoney(contract.paymentRub)} /> : null}
      <Anchor
        href={resolveUrl(getGetContractDocumentUrl(contract.id))}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t.document}
      </Anchor>
      <Text size="sm" c="dimmed">
        {t.demo}
      </Text>
      <Text role="status">{fill(t.progress, { ...contract.progress })}</Text>
      {contract.signers.map((signer, index) => (
        <Group key={`${signer.role}:${index}`} justify="space-between">
          <Text>{signer.name}</Text>
          <Badge color={signer.signed ? 'green' : 'gray'}>
            {signer.signed ? t.signed : t.waitingSignature}
          </Badge>
        </Group>
      ))}
      {query.isError ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {signed ? (
        <Alert color={status === 'DISBURSED' ? 'green' : 'blue'} role="status">
          {delivery}
        </Alert>
      ) : null}
      {contract.canSign ? (
        <SigningForm
          key={contract.id}
          contract={contract}
          onSigned={onSigned}
          refresh={() => void query.refetch()}
        />
      ) : null}
      {!signed && !contract.canSign ? <Text size="sm">{t.cannotSign}</Text> : null}
      {contract.canPassToDirector ? (
        <>
          {pass.error ? <ProblemAlert error={pass.error} /> : null}
          {passed ? (
            <Alert color="green">{t.passed}</Alert>
          ) : (
            <div>
              <Button
                variant="light"
                loading={pass.isPending}
                onClick={() => void passToDirector()}
              >
                {t.pass}
              </Button>
            </div>
          )}
        </>
      ) : null}
    </Stack>
  );
}

/** После перезагрузки находим сохранённый договор через предложение, без локального состояния. */
export function ContractSigning({ applicationId }: { applicationId: string }) {
  const query = useGetApplicationOffer(applicationId, {
    query: { select: (result) => (result.status === 200 ? result.data : undefined) },
  });
  const contractId = query.data?.contractId;
  if (contractId)
    return <ContractView key={contractId} applicationId={applicationId} contractId={contractId} />;
  if (query.isPending)
    return (
      <Group role="status">
        <Loader size="sm" />
        <Text>{t.loading}</Text>
      </Group>
    );
  return query.isError ? (
    <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
  ) : (
    <Stack>
      <Text>{t.missing}</Text>
      <Button variant="light" onClick={() => void query.refetch()}>
        {t.refresh}
      </Button>
    </Stack>
  );
}
