import { lazy, Suspense } from 'react';
import { Splash } from './screens';

// React.lazy запускается после RequireDemo. RouteObject.lazy подгружает код до проверки гейта.
const DemoZoneLayout = lazy(async () => ({
  default: (await import('@/features/demo/DemoZoneLayout')).DemoZoneLayout,
}));
const DemoPage = lazy(async () => ({
  default: (await import('@/features/demo/DemoZoneLayout')).DemoPage,
}));

export function DemoLayoutRoute() {
  return (
    <Suspense fallback={<Splash />}>
      <DemoZoneLayout />
    </Suspense>
  );
}

export function DemoPageRoute() {
  return (
    <Suspense fallback={<Splash />}>
      <DemoPage />
    </Suspense>
  );
}
