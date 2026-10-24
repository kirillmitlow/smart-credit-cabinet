import { useMemo, useState } from 'react';
import { Group, Loader, NumberInput, Slider, Stack, Text, Title } from '@mantine/core';
import type { PaymentRequest, ProductOut } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { VariantCard } from '@/components/VariantCard';
import { formatMoney } from '@/lib/format';
import { usePaymentPreview } from '@/lib/usePaymentPreview';
import { catalogTexts as t, fill } from '@/texts';

export function ProductCalculator({ product }: { product: ProductOut }) {
  const [amount, setAmount] = useState<number | string>(
    Math.max(product.amountMinRub, Math.min(500_000, product.amountMaxRub)),
  );
  const [term, setTerm] = useState<number | string>(
    Math.max(product.termMinMonths, Math.min(12, product.termMaxMonths)),
  );
  const validAmount =
    typeof amount === 'number' &&
    Number.isSafeInteger(amount) &&
    amount >= product.amountMinRub &&
    amount <= product.amountMaxRub;
  const validTerm =
    typeof term === 'number' &&
    Number.isInteger(term) &&
    term >= product.termMinMonths &&
    term <= product.termMaxMonths;
  const request = useMemo<PaymentRequest | null>(
    () =>
      validAmount && validTerm && typeof amount === 'number' && typeof term === 'number'
        ? { productCode: product.code, amountRub: amount, termMonths: term }
        : null,
    [validAmount, validTerm, amount, term, product.code],
  );
  const { data, pending, error, refetch } = usePaymentPreview(request);
  const revolving = ['LINE', 'OVERDRAFT'].includes(product.repayment);
  const amountRange = fill(t.amountRange, {
    min: formatMoney(product.amountMinRub),
    max: formatMoney(product.amountMaxRub),
  });
  const termRange = fill(t.termRange, { min: product.termMinMonths, max: product.termMaxMonths });
  return (
    <Stack gap="md" component="section" aria-labelledby="product-calculator-title">
      <Title order={2} id="product-calculator-title">
        {t.calculator}
      </Title>
      <NumberInput
        label={revolving ? t.limit : t.amount}
        value={amount}
        onChange={setAmount}
        min={product.amountMinRub}
        max={product.amountMaxRub}
        clampBehavior="none"
        allowNegative={false}
        decimalScale={0}
        thousandSeparator=" "
        description={amountRange}
        error={!validAmount ? amountRange : undefined}
      />
      <Slider
        thumbLabel={t.amountSlider}
        min={product.amountMinRub}
        max={product.amountMaxRub}
        step={Math.min(50_000, Math.max(1, product.amountMaxRub - product.amountMinRub))}
        value={
          typeof amount === 'number'
            ? Math.max(product.amountMinRub, Math.min(amount, product.amountMaxRub))
            : product.amountMinRub
        }
        onChange={setAmount}
        label={formatMoney}
        disabled={product.amountMinRub === product.amountMaxRub}
      />
      <NumberInput
        label={t.term}
        value={term}
        onChange={setTerm}
        min={product.termMinMonths}
        max={product.termMaxMonths}
        clampBehavior="none"
        allowNegative={false}
        decimalScale={0}
        description={termRange}
        error={!validTerm ? termRange : undefined}
      />
      <Slider
        thumbLabel={t.termSlider}
        min={product.termMinMonths}
        max={product.termMaxMonths}
        step={1}
        value={
          typeof term === 'number'
            ? Math.max(product.termMinMonths, Math.min(term, product.termMaxMonths))
            : product.termMinMonths
        }
        onChange={setTerm}
        disabled={product.termMinMonths === product.termMaxMonths}
      />
      {pending ? (
        <Group gap="xs" role="status">
          <Loader size="xs" />
          <Text>{t.calculating}</Text>
        </Group>
      ) : null}
      {error ? <ProblemAlert error={error} onAction={() => void refetch()} /> : null}
      <div aria-live="polite" data-testid="catalog-calculation">
        <VariantCard
          id={`catalog-${product.code}`}
          headingLevel={3}
          title={product.title}
          amountRub={!revolving && validAmount ? Number(amount) : null}
          termMonths={validTerm ? Number(term) : null}
          paymentRub={data?.paymentRub}
          paymentKind={data?.paymentKind}
          overpaymentRub={revolving ? null : data?.overpaymentRub}
          ratePercentFrom={data?.ratePercentFrom ?? product.ratePercentFrom}
          approximate
          needsContract={product.requiresContract}
          needsSecurity={product.requiresSecurity}
          documents={product.documents}
          note={t.approximate}
        />
        {data && product.repayment === 'BULLET' ? (
          <Text mt="sm">{fill(t.lastPayment, { amount: formatMoney(data.lastPaymentRub) })}</Text>
        ) : null}
        {revolving ? <Text mt="sm">{t.revolving}</Text> : null}
        {data && revolving ? (
          <Text>{fill(t.revolvingInterest, { amount: formatMoney(data.overpaymentRub) })}</Text>
        ) : null}
      </div>
    </Stack>
  );
}
