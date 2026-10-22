import { useQueryClient } from '@tanstack/react-query';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';
import { useLogout } from '@/api/generated/api';
import { Shell } from '@/components/Shell';
import { usePublicConfig, useSession } from '@/features/auth/session';
import { shell } from '@/texts';

/** Оболочка клиентской зоны. Пункт «Демо-панель» есть в меню, только пока включён DEMO_MODE */
export function ClientLayout() {
  const me = useSession('client').data;
  const config = usePublicConfig().data;
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useLogout();
  const companies = me?.companies ?? [];
  const active = (companies.find((item) => item.company.id === me?.activeCompanyId) ?? companies[0])
    ?.company;
  const isGuarantor = me?.role === 'GUARANTOR';

  // Компаний несколько, а активной нет (вход без выбора): сначала выбор, потом всё остальное
  if (
    me &&
    me.activeCompanyId === null &&
    companies.length > 1 &&
    location.pathname !== '/company'
  ) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/company?next=${encodeURIComponent(next)}`} replace />;
  }

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

  const onLogout = () => {
    // Выходим в любом случае: данные прошлого человека в кэше не должны достаться следующему
    logout.mutate(undefined, {
      onSettled: () => {
        void navigate('/login', { replace: true });
        queryClient.clear();
      },
    });
  };

  return (
    <Shell
      zone="client"
      homeHref="/"
      nav={nav}
      userName={me?.displayName ?? null}
      companyName={active?.name ?? null}
      canSwitchCompany={companies.length > 1}
      onLogout={onLogout}
    >
      <Outlet />
    </Shell>
  );
}
