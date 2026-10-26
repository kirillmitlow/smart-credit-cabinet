import { Component, type ErrorInfo, type ReactNode } from 'react';
import { ErrorScreen } from '@/components/ErrorScreen';
import { toAppError } from '@/api/errors';
import { errorView, guards } from '@/texts';

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
  failed: boolean;
}

/**
 * Последний рубеж: ошибка отрисовки не оставляет белый экран. Показывает общий экран ошибки
 * (с демо-плашкой: она нужна на любом скриншоте) и кнопку «Повторить».
 */
export class AppErrorBoundary extends Component<Props, State> {
  override state: State = { error: null, failed: false };

  static getDerivedStateFromError(error: unknown): State {
    return { error, failed: true };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    // Единственный след в консоли для разработчика; пользователю показываем словарный текст
    console.error('Render error', error, info.componentStack);
  }

  private retry = () => {
    this.setState({ error: null, failed: false });
  };

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    const view = errorView(toAppError(this.state.error));
    return (
      <ErrorScreen
        title={guards.generalError.title}
        body={view.text}
        requestId={view.requestId}
        onRetry={this.retry}
      />
    );
  }
}
