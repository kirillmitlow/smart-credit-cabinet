import { createBrowserRouter, type RouteObject } from 'react-router';
import { PlaceholderPage } from '@/components/PlaceholderPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { HomePage } from '@/features/home/HomePage';
import { placeholders } from '@/texts';
import { ClientLayout } from './ClientLayout';
import { RequireBank, RequireClient, RequireDemo } from './guards';
import { RootLayout } from './RootLayout';
import { NotFoundScreen, RouteErrorScreen } from './screens';

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
                      Component: (await import('@/features/backoffice/BankPages')).BankQueuePage,
                    }),
                  },
                  {
                    path: 'applications/:id',
                    lazy: async () => ({
                      Component: (await import('@/features/backoffice/BankPages'))
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
                lazy: async () => ({
                  Component: (await import('@/features/demo/DemoZoneLayout')).DemoZoneLayout,
                }),
                children: [
                  {
                    index: true,
                    lazy: async () => ({
                      Component: (await import('@/features/demo/DemoZoneLayout')).DemoPage,
                    }),
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
                  { path: 'company', element: <PlaceholderPage content={placeholders.company} /> },
                  { path: 'wizard', element: <PlaceholderPage content={placeholders.wizard} /> },
                  {
                    path: 'wizard/result',
                    element: <PlaceholderPage content={placeholders.wizardResult} />,
                  },
                  {
                    path: 'products',
                    element: <PlaceholderPage content={placeholders.products} />,
                  },
                  {
                    path: 'products/:code',
                    element: <PlaceholderPage content={placeholders.product} />,
                  },
                  {
                    path: 'applications/:id',
                    element: <PlaceholderPage content={placeholders.application} />,
                  },
                  {
                    path: 'applications/:id/edit/:step',
                    element: <PlaceholderPage content={placeholders.applicationEdit} />,
                  },
                  {
                    path: 'applications/:id/offer',
                    element: <PlaceholderPage content={placeholders.offer} />,
                  },
                  {
                    path: 'applications/:id/sign',
                    element: <PlaceholderPage content={placeholders.sign} />,
                  },
                  { path: 'loans', element: <PlaceholderPage content={placeholders.loans} /> },
                  { path: 'loans/:id', element: <PlaceholderPage content={placeholders.loan} /> },
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
