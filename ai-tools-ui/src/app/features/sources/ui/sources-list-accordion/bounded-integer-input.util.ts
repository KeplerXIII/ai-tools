export function clampBoundedInteger(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
): number {
  const raw = Number(value);
  if (!Number.isFinite(raw)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.floor(raw)));
}

export function onBoundedIntegerKeyDown(event: KeyboardEvent, min: number, max: number): void {
  const controlKeys = [
    'Backspace',
    'Delete',
    'Tab',
    'Escape',
    'Enter',
    'ArrowLeft',
    'ArrowRight',
    'ArrowUp',
    'ArrowDown',
    'Home',
    'End',
  ];
  if (controlKeys.includes(event.key) || event.ctrlKey || event.metaKey) {
    return;
  }
  if (!/^\d$/.test(event.key)) {
    event.preventDefault();
    return;
  }
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) {
    return;
  }
  const start = input.selectionStart ?? 0;
  const end = input.selectionEnd ?? 0;
  const next = `${input.value.slice(0, start)}${event.key}${input.value.slice(end)}`;
  if (next === '') {
    return;
  }
  const n = Number.parseInt(next, 10);
  if (!Number.isFinite(n) || n < min || n > max) {
    event.preventDefault();
  }
}
