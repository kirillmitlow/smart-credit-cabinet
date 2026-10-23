import { useQueryClient } from '@tanstack/react-query';
import { Outlet, useNavigate } from 'react-router';
import { useBankLogout } from '@/api/generated/api';
import { sessionQueryKey } from '@/api/session-keys';
import { ProblemAlert } from '@/components/ProblemAlert';
import { Shell } from '@/components/Shell';
import { useSession } from '@/features/auth/session';
import { shell } from '@/texts';

/** Оболочка банка: другая цветовая полоса и подпись «Рабочее место банка (демо)», нельзя спутать с клиентской */
export function BankZoneLayout() {
  const me = useSession('bank').data;
  const navigate = useNavigate();
  const cache = useQueryClient();
  const logout = useBankLogout();
  const onLogout = () => {
    if (logout.isPending) return;
    logout.mutate(undefined, {
      onSuccess: () => {
        const bankQueries = {
          predicate: (query: { queryKey: readonly unknown[] }) =>
            query.queryKey.some((part) => typeof part === 'string' && part.includes('/backoffice')),
        };
        void cache.cancelQueries(bankQueries).then(() => {
          cache.removeQueries(bankQueries);
          cache.setQueryData(sessionQueryKey('bank'), null);
          void navigate('/login?zone=bank', { replace: true });
        });
      },
    });
  };
  return (
    <Shell
      zone="bank"
      homeHref="/bank"
      nav={[{ to: '/bank', label: shell.nav.bankQueue, end: true }]}
      userName={me?.displayName ?? null}
      onLogout={onLogout}
    >
      {logout.isError ? <ProblemAlert error={logout.error} onAction={onLogout} /> : null}
      <Outlet />
    </Shell>
  );
}
