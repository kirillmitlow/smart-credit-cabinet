import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';
import { DemoPanel } from './DemoPanel';
import { shell } from '@/texts';

/** Оболочка демо-панели: служебный вид с пометкой «Только для проверки» (60-05) */
export function DemoZoneLayout() {
  return (
    <Shell
      zone="demo"
      homeHref="/"
      nav={[
        { to: '/', label: shell.nav.clientZone, end: true },
        { to: '/demo', label: shell.nav.demo },
      ]}
    >
      <Outlet />
    </Shell>
  );
}

/** Демо-панель (60-05). Содержимое делает T-435 */
export function DemoPage() {
  return <DemoPanel />;
}
