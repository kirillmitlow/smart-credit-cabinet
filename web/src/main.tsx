import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';
import '@fontsource-variable/onest/wght.css';
import '@fontsource-variable/unbounded/wght.css';
import '@mantine/core/styles.css';
import './styles.css';
import { createQueryClient } from '@/api/query-client';
import { AppProviders } from '@/app/AppProviders';
import { createAppRouter } from '@/app/router';

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element #root not found');

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders queryClient={createQueryClient()}>
      <RouterProvider router={createAppRouter()} />
    </AppProviders>
  </StrictMode>,
);
