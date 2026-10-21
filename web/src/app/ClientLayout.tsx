import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';
import { usePublicConfig, useSession } from '@/features/auth/session';
import { shell } from '@/texts';

/** Оболочка клиентской зоны. Пункт «Демо-панель» есть в меню, только пока включён DEMO_MODE */
export function ClientLayout() {
  const me = useSession('client').data;
  const config = usePublicConfig().data;
  const companies = me?.companies ?? [];
  const active = companies.find((company) => company.id === me?.activeCompanyId) ?? companies[0];
  const isGuarantor = me?.role === 'GUARANTOR';

  const nav = isGuarantor
    ? []
    : [
        { to: '/', label: shell.nav.home, end: true },
        { to: '/wizard', label: shell.nav.wizard },
        { to: '/products', label: shell.nav.products },
        { to: '/loans', label: shell.nav.loans },
        { to: '/notifications', label: shell.nav.notifications },
        ...(config?.demoMode ? [{ to: '/demo', label: shell.nav.demo }] : []),
      ];

  return (
    <Shell
      zone="client"
      homeHref="/"
      nav={nav}
      userName={me?.user.name ?? null}
      companyName={active?.name ?? null}
      canSwitchCompany={companies.length > 1}
    >
      <Outlet />
    </Shell>
  );
}
