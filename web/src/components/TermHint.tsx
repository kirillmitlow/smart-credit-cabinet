import { Tooltip, UnstyledButton } from '@mantine/core';

export interface TermHintProps {
  /** Слово из словаря подсказок (`termHints.*`): само слово и объяснение в 1–2 предложения */
  hint: { readonly term: string; readonly hint: string };
  /** Как слово выглядит в тексте; по умолчанию как в словаре */
  label?: string;
}

/**
 * Слово с пунктирным подчёркиванием (60-06): по наведению и по Tab рядом появляется объяснение.
 * Это кнопка, поэтому до слова можно дойти клавишей Tab.
 */
export function TermHint({ hint, label }: TermHintProps) {
  return (
    <Tooltip
      label={hint.hint}
      multiline
      w={280}
      withArrow
      events={{ hover: true, focus: true, touch: true }}
    >
      <UnstyledButton
        type="button"
        fz="inherit"
        fw="inherit"
        style={{ textDecoration: 'underline dotted', textUnderlineOffset: 3, cursor: 'help' }}
      >
        {label ?? hint.term}
      </UnstyledButton>
    </Tooltip>
  );
}
