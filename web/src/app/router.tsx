import { createBrowserRouter, type RouteObject } from 'react-router';
import { LoginPage } from '@/features/auth/LoginPage';
import { ApplicationEditPage } from '@/features/application/ApplicationEditPage';
import { ApplicationPage } from '@/features/application/ApplicationPage';
import { CompanyPage } from '@/features/auth/CompanyPage';
import { HomePage } from '@/features/home/HomePage';
import { LoanPage } from '@/features/loans/LoanPage';
import { LoansPage } from '@/features/loans/LoansPage';
import { WizardPage } from '@/features/wizard/WizardPage';
import { WizardResultPage } from '@/features/wizard/WizardResultPage';
import { ClientLayout } from './ClientLayout';
import { RequireBank, RequireClient, RequireDemo } from './guards';
import { RootLayout } from './RootLayout';
import { NotFoundScreen, RouteErrorScreen } from './screens';
import { DemoLayoutRoute, DemoPageRoute } from './DemoRoutes';

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
                element: <DemoLayoutRoute />,
                children: [
                  {
                    index: true,
                    element: <DemoPageRoute />,
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
                  { path: 'applications/:id', element: <ApplicationPage /> },
                  { path: 'applications/:id/edit/:step', element: <ApplicationEditPage /> },
                  { path: 'loans', element: <LoansPage /> },
                  { path: 'loans/:id', element: <LoanPage /> },
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
