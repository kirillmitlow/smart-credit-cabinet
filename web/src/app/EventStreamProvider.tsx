import { useCallback, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router';
import { sessionQueryKey } from '@/api/session-keys';
import { zoneFromPath } from '@/api/zone';
import { loginUrl } from '@/features/auth/loginUrl';
import { useSession } from '@/features/auth/session';
import { ConnectionContext } from '@/lib/events/connection-context';
import { useEventStream } from '@/lib/events/useEventStream';

/**
 * Открывает один поток событий на вкладку, пока в текущей зоне есть сессия, и отдаёт состояние связи
 * индикатору в шапке. `auth_expired` ведёт на экран входа с сообщением «Сессия закончилась».
 */
export function EventStreamProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const zone = zoneFromPath(location.pathname);
  const session = useSession(zone);
  const pathname = location.pathname;
  const search = location.search;

  const onAuthExpired = useCallback(() => {
    void navigate(loginUrl(zone, { pathname, search }, 'expired'), { replace: true });
    queryClient.setQueryData(sessionQueryKey(zone), null);
  }, [navigate, queryClient, zone, pathname, search]);

  const status = useEventStream({ zone, enabled: Boolean(session.data), onAuthExpired });
  return <ConnectionContext value={status}>{children}</ConnectionContext>;
}
