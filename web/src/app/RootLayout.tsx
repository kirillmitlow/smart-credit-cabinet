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
export function RootLayout() {
  return (
    <EventStreamProvider>
      <a className="skip-link" href="#main">
        {shell.skipToContent}
      </a>
      <OfflineBar />
      <DemoBanner />
      <DesktopHint />
      <Outlet />
    </EventStreamProvider>
  );
}
