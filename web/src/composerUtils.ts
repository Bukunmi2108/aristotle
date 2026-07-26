export const MAX_PROMPT_LENGTH = 12_000;

export function promptCharactersRemaining(value: string): number {
  return MAX_PROMPT_LENGTH - value.length;
}

export function insertPastedText(
  value: string,
  pastedText: string,
  selectionStart: number,
  selectionEnd: number,
): { value: string; cursor: number; truncated: boolean } {
  const availableCharacters =
    MAX_PROMPT_LENGTH - (value.length - (selectionEnd - selectionStart));
  const acceptedText = pastedText.slice(0, Math.max(0, availableCharacters));
  return {
    value:
      value.slice(0, selectionStart) +
      acceptedText +
      value.slice(selectionEnd),
    cursor: selectionStart + acceptedText.length,
    truncated: acceptedText.length < pastedText.length,
  };
}

export function shouldSubmitComposerKey({
  key,
  shiftKey,
  isComposing,
}: {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
}): boolean {
  return key === "Enter" && !shiftKey && !isComposing;
}
