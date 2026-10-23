import { lazy, Suspense } from 'react';
import { usePublicConfig } from '@/features/auth/session';
import { Outlet } from 'react-router';
import { DemoBanner } from '@/components/DemoBanner';
import { DesktopHint } from '@/components/DesktopHint';
import { OfflineBar } from '@/components/OfflineBar';
import { shell } from '@/texts';
import { EventStreamProvider } from './EventStreamProvider';

/**
 * Корневая раскладка всех зон и всех экранов, включая вход и ошибки: сверху «Нет связи» (если сети нет),
 * постоянная демо-плашка и подсказка про узкий экран; под ними — зона.
 */
const DemoTools = lazy(() => import('@/features/demo/DemoTools'));

export function RootLayout() {
  const demoEnabled = usePublicConfig().data?.demoMode === true;
  return (
    <EventStreamProvider>
      <a className="skip-link" href="#main">
        {shell.skipToContent}
      </a>
      <OfflineBar />
      <DemoBanner />
      <DesktopHint />
      {demoEnabled ? (
        <Suspense fallback={null}>
          <DemoTools />
        </Suspense>
      ) : null}
      <Outlet />
    </EventStreamProvider>
  );
}
