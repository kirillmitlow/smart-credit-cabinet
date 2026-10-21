import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';
import { useSession } from '@/features/auth/session';
import { shell } from '@/texts';

/** Оболочка банка: другая цветовая полоса и подпись «Рабочее место банка (демо)», нельзя спутать с клиентской */
export function BankZoneLayout() {
  const me = useSession('bank').data;
  return (
    <Shell
      zone="bank"
      homeHref="/bank"
      nav={[{ to: '/bank', label: shell.nav.bankQueue, end: true }]}
      userName={me?.displayName ?? null}
    >
      <Outlet />
    </Shell>
  );
}
