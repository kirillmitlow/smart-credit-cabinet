import {
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Link, useParams } from 'react-router';
import { useListProducts } from '@/api/generated/api';
import type { ProductOut } from '@/api/generated/model';
import { NotFoundScreen } from '@/app/screens';
import { ErrorScreen } from '@/components/ErrorScreen';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useSession } from '@/features/auth/session';
import { formatDateLong, formatMoney, formatPercent, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { catalogTexts as t, errorView, fill, productNames, shell } from '@/texts';
import { ProductCalculator } from './ProductCalculator';

function Requirements({ product }: { product: ProductOut }) {
  return (
    <Stack gap={4}>
      {product.requiresBankCustomer ? <Text size="sm">{t.bankCustomer}</Text> : null}
      {product.requiresContract ? <Text size="sm">{t.contract}</Text> : null}
      {product.requiresSecurity ? <Text size="sm">{t.security}</Text> : null}
      {product.collateralRequiredAboveRub !== null ? (
        <Text size="sm">
          {fill(t.securedAbove, { amount: formatMoney(product.collateralRequiredAboveRub) })}
        </Text>
      ) : null}
      {product.unavailableReasons.map((reason) => (
        <Stack gap={2} key={reason.code}>
          <Text size="sm">{reason.text}</Text>
          {reason.action ? <Text size="sm">{reason.action}</Text> : null}
          {reason.availableFrom ? (
            <Text size="sm" fw={600}>
              {fill(t.availableFrom, {
                date: formatDateLong(reason.availableFrom, { withYear: true }),
              })}
            </Text>
          ) : null}
        </Stack>
      ))}
      {product.hint ? (
        <Text size="sm" fw={600}>
          {product.hint}
        </Text>
      ) : null}
    </Stack>
  );
}

export function CatalogPage() {
  const { code } = useParams();
  const session = useSession('client');
  const blocked = session.data?.role === 'GUARANTOR';
  const validCode = code === undefined || Object.hasOwn(productNames, code);
  const query = useListProducts({
    query: {
      enabled: !blocked && validCode,
      select: (response) => {
        if (response.status !== 200) throw new Error('Unexpected catalog response');
        return response.data.items;
      },
    },
  });
  const selected = query.data?.find((product) => product.code === code);
  const heading = usePageHeading(selected?.title ?? t.title);
  if (blocked || !validCode) return <NotFoundScreen />;
  if (query.isPending)
    return (
      <Center py="xl" role="status">
        <Loader size="sm" mr="sm" />
        {shell.loading}
      </Center>
    );
  if (!query.data) {
    const view = errorView(query.error);
    return (
      <ErrorScreen
        title={t.failed}
        body={view.text}
        requestId={view.requestId}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (code && !selected) return <NotFoundScreen />;
  return (
    <Stack gap="lg">
      <Title order={1} ref={heading} tabIndex={-1}>
        {selected?.title ?? t.title}
      </Title>
      <Group>
        {selected ? (
          <Button component={Link} to="/products" variant="subtle">
            {t.all}
          </Button>
        ) : (
          <Text>{t.intro}</Text>
        )}
        <Button component={Link} to="/wizard" variant="light">
          {t.wizard}
        </Button>
      </Group>
      {query.isError ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {selected ? (
        <>
          <Text>{selected.purpose}</Text>
          <Requirements product={selected} />
          <ProductCalculator key={selected.code} product={selected} />
        </>
      ) : query.data.length === 0 ? (
        <Text>{t.empty}</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
          {query.data.map((product) => (
            <Card
              key={product.code}
              component="article"
              withBorder
              bg={product.available ? undefined : 'gray.1'}
            >
              <Stack gap="sm">
                <Title order={2} size="h3">
                  {product.title}
                </Title>
                <Badge variant="light" color={product.available ? 'green' : 'gray'} c="dark.9">
                  {product.available ? t.available : t.unavailable}
                </Badge>
                <Text>{product.purpose}</Text>
                <Text fw={600}>
                  {fill(t.amountRange, {
                    min: formatMoney(product.amountMinRub),
                    max: formatMoney(product.amountMaxRub),
                  })}
                </Text>
                <Text>
                  {formatTermMonths(product.termMinMonths)} —{' '}
                  {formatTermMonths(product.termMaxMonths)}
                </Text>
                <Text>{fill(t.rate, { rate: formatPercent(product.ratePercentFrom) })}</Text>
                <Requirements product={product} />
                <Button component={Link} to={`/products/${product.code}`} variant="light">
                  {t.details}
                </Button>
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
