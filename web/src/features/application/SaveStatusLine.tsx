import { Button, Group, Text } from '@mantine/core';
import { useOnline } from '@/lib/useOnline';
import { formatTime } from '@/lib/format';
import { applicationForm, errorView, fill } from '@/texts';
import type { SaveState } from './useDraftAutosave';

/**
 * Строка «Сохранено в 12:04» под шагами. Область `status` есть всегда, поэтому смена
 * состояния озвучивается скринридером вежливо, без перебивания набора.
 */
export function SaveStatusLine({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  const online = useOnline();
  let text: string = applicationForm.notSavedYet;
  let retry = false;
  if (!online) {
    text = applicationForm.offlinePaused;
  } else if (state.kind === 'saving') {
    text = applicationForm.saving;
  } else if (state.kind === 'saved') {
    text = fill(applicationForm.savedAt, { time: formatTime(state.at) });
  } else if (state.kind === 'error') {
    text = `${applicationForm.saveFailed} ${errorView(state.error).text}`;
    retry = true;
  }
  return (
    <Group gap="sm" role="status" aria-live="polite" data-testid="save-status">
      <Text size="sm" c="dimmed">
        {text}
      </Text>
      {retry ? (
        <Button size="compact-sm" variant="light" onClick={onRetry}>
          {applicationForm.saveRetry}
        </Button>
      ) : null}
    </Group>
  );
}
