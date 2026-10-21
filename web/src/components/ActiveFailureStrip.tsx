import { Alert } from '@mantine/core';
import { fill, shell } from '@/texts';

export interface ActiveFailureStripProps {
  /** Названия включённых сбоев; пусто — полосы нет. Список наполнит демо-панель (T-435) */
  failures?: readonly string[];
}

/** Слот «Полоса активного сбоя» (60-05): виден во всех зонах, пока демо-сбой включён */
export function ActiveFailureStrip({ failures = [] }: ActiveFailureStripProps) {
  if (failures.length === 0) return null;
  return (
    <Alert color="yellow" radius={0} role="status" aria-label={shell.failureStrip.label}>
      {failures.map((name) => (
        <div key={name}>{fill(shell.failureStrip.one, { name })}</div>
      ))}
    </Alert>
  );
}
