import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useHealthLive } from '@/api/generated/api';
import { getHealthLiveMockHandler } from '@/api/generated/api.msw';
import { ProblemAlert } from '@/components/ProblemAlert';
import { problemResponse } from '@/test/factories';
import { renderWithProviders } from '@/test/render';
import { server } from '@/test/server';
import { http } from 'msw';
import { errorTexts } from '@/texts';

/** Сгенерированный orval-хук проходит через общий обработчик: префикс /api, заголовки, AppError */
function Health() {
  const { data, error } = useHealthLive();
  if (error) return <ProblemAlert error={error} />;
  return <output>{data ? `${data.status}:${data.data.status}` : 'loading'}</output>;
}

describe('сгенерированный клиент', () => {
  it('хук получает данные по схеме через обработчик MSW из orval', async () => {
    server.use(getHealthLiveMockHandler({ status: 'ok' }));
    renderWithProviders(<Health />);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('200:ok'));
  });

  it('ошибка сервера доходит до экрана как AppError с текстом из словаря', async () => {
    server.use(
      http.get('*/api/health/live', () =>
        problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE', requestId: 'req-health' }),
      ),
    );
    renderWithProviders(<Health />);
    expect(await screen.findByText(errorTexts.SERVICE_UNAVAILABLE.text)).toBeInTheDocument();
    expect(screen.getByText(/req-health/)).toBeInTheDocument();
  });
});
