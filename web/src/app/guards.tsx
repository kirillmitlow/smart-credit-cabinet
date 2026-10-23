import { Navigate, Outlet, useLocation } from 'react-router';
import { loginUrl } from '@/features/auth/loginUrl';
import { isBankRole, usePublicConfig, useSession } from '@/features/auth/session';
import {
  BankOnlyScreen,
  ClientOnlyScreen,
  NotFoundScreen,
  SessionCheckFailed,
  Splash,
} from './screens';

/**
 * Защита маршрутов (60-01): интерфейс скрывает лишнее, решает сервер. Сессия нужна для удобства
 * (не показывать кнопку, которая вернёт 403), а не для безопасности.
 */

/** Зона клиента: нужна клиентская сессия; отдельный кабинет поручителя пока не поддерживается. */
export function RequireClient() {
  const location = useLocation();
  const session = useSession('client');

  if (session.isPending) return <Splash />;
  if (session.isError) {
    return (
      <SessionCheckFailed
        error={session.error}
        onRetry={() => {
          void session.refetch();
        }}
      />
    );
  }
  const me = session.data;
  if (!me) return <Navigate to={loginUrl('client', location)} replace />;
  if (isBankRole(me.role)) return <ClientOnlyScreen />;
  if (me.role === 'GUARANTOR') return <NotFoundScreen />;
  return <Outlet />;
}

/**
 * Зона банка: сессия `sid_bank` отдельная от клиентской (D-085). Клиент, который открыл `/bank`,
 * видит объяснение «Эта часть для сотрудников банка», а не тихий переход.
 */
export function RequireBank() {
  const location = useLocation();
  const bank = useSession('bank');
  const bankMissing = bank.data === null;
  const client = useSession('client', bankMissing);

  if (bank.isPending) return <Splash />;
  if (bank.isError) {
    return (
      <SessionCheckFailed
        error={bank.error}
        onRetry={() => {
          void bank.refetch();
        }}
      />
    );
  }

  const loginHref = loginUrl('bank', location);
  if (bank.data) {
    return isBankRole(bank.data.role) ? <Outlet /> : <BankOnlyScreen loginHref={loginHref} />;
  }
  if (client.isPending) return <Splash />;
  if (client.data) return <BankOnlyScreen loginHref={loginHref} />;
  return <Navigate to={loginHref} replace />;
}

/** `/demo` существует, только пока включён `DEMO_MODE` (публичная настройка); сессия не нужна (Q-090) */
export function RequireDemo() {
  const config = usePublicConfig();
  if (config.isPending) return <Splash />;
  if (config.isError) {
    return (
      <SessionCheckFailed
        error={config.error}
        onRetry={() => {
          void config.refetch();
        }}
      />
    );
  }
  if (!config.data.demoMode) return <NotFoundScreen kind="demo" />;
  return <Outlet />;
}
