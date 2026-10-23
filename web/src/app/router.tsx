import { lazy, Suspense } from 'react';
import { createBrowserRouter, type RouteObject } from 'react-router';
import { PlaceholderPage } from '@/components/PlaceholderPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { ApplicationEditPage } from '@/features/application/ApplicationEditPage';
import { ApplicationPage } from '@/features/application/ApplicationPage';
import { CompanyPage } from '@/features/auth/CompanyPage';
import { HomePage } from '@/features/home/HomePage';
import { LoanPage } from '@/features/loans/LoanPage';
import { LoansPage } from '@/features/loans/LoansPage';
import { WizardPage } from '@/features/wizard/WizardPage';
import { WizardResultPage } from '@/features/wizard/WizardResultPage';
import { placeholders } from '@/texts';
import { ClientLayout } from './ClientLayout';
import { RequireBank, RequireClient, RequireDemo } from './guards';
import { RootLayout } from './RootLayout';
import { NotFoundScreen, RouteErrorScreen, Splash } from './screens';

// React.lazy запускается после RequireDemo. RouteObject.lazy подгружает код до проверки гейта.
const DemoZoneLayout = lazy(async () => ({
  default: (await import('@/features/demo/DemoZoneLayout')).DemoZoneLayout,
}));
const DemoPage = lazy(async () => ({
  default: (await import('@/features/demo/DemoZoneLayout')).DemoPage,
}));

/**
 * Карта адресов (60-01). Три зоны одного SPA:
 * - `/login` и клиент (`/` и всё, что не `/bank` и не `/demo`);
 * - `/bank/*`: другая оболочка и своя сессия; код зоны подгружается отдельным куском (lazy), клиент его не скачивает;
 * - `/demo`: только при включённом DEMO_MODE; тоже отдельный кусок.
 * Исходы заявки (одобрено, встречное, отказ…) — не адреса, а состояния одной страницы `/applications/:id`.
 */
export const appRoutes: RouteObject[] = [
  {
    element: <RootLayout />,
    children: [
      {
        // Ошибка внутри маршрута показывается под общей раскладкой: демо-плашка остаётся на экране
        errorElement: <RouteErrorScreen />,
        children: [
          { path: '/login', element: <LoginPage /> },
          {
            path: '/bank',
            element: <RequireBank />,
            children: [
              {
                lazy: async () => ({
                  Component: (await import('@/features/backoffice/BankZoneLayout')).BankZoneLayout,
                }),
                children: [
                  {
                    index: true,
                    lazy: async () => ({
                      Component: (await import('@/features/bank/BankQueuePage')).BankQueuePage,
                    }),
                  },
                  {
                    path: 'applications/:id',
                    lazy: async () => ({
                      Component: (await import('@/features/bank/BankApplicationPage'))
                        .BankApplicationPage,
                    }),
                  },
                  { path: '*', element: <NotFoundScreen /> },
                ],
              },
            ],
          },
          {
            path: '/demo',
            element: <RequireDemo />,
            children: [
              {
                element: (
                  <Suspense fallback={<Splash />}>
                    <DemoZoneLayout />
                  </Suspense>
                ),
                children: [
                  {
                    index: true,
                    element: (
                      <Suspense fallback={<Splash />}>
                        <DemoPage />
                      </Suspense>
                    ),
                  },
                  { path: '*', element: <NotFoundScreen kind="demo" /> },
                ],
              },
            ],
          },
          {
            element: <RequireClient />,
            children: [
              {
                element: <ClientLayout />,
                children: [
                  { index: true, element: <HomePage /> },
                  { path: 'company', element: <CompanyPage /> },
                  { path: 'wizard', element: <WizardPage /> },
                  { path: 'wizard/result', element: <WizardResultPage /> },
                  {
                    path: 'products',
                    element: <PlaceholderPage content={placeholders.products} />,
                  },
                  {
                    path: 'products/:code',
                    element: <PlaceholderPage content={placeholders.product} />,
                  },
                  { path: 'applications/:id', element: <ApplicationPage /> },
                  { path: 'applications/:id/edit/:step', element: <ApplicationEditPage /> },
                  {
                    path: 'applications/:id/offer',
                    element: <PlaceholderPage content={placeholders.offer} />,
                  },
                  {
                    path: 'applications/:id/sign',
                    element: <PlaceholderPage content={placeholders.sign} />,
                  },
                  { path: 'loans', element: <LoansPage /> },
                  { path: 'loans/:id', element: <LoanPage /> },
                  {
                    path: 'notifications',
                    element: <PlaceholderPage content={placeholders.notifications} />,
                  },
                  {
                    path: 'guarantee',
                    element: <PlaceholderPage content={placeholders.guarantee} />,
                  },
                  { path: '*', element: <NotFoundScreen /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(appRoutes);
}
