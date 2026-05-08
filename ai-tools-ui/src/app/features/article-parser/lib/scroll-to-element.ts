import { ChangeDetectorRef, ElementRef } from '@angular/core';

export function scrollToElement(
  getElement: () => ElementRef | undefined,
  cdr: ChangeDetectorRef,
): void {
  setTimeout(() => {
    cdr.detectChanges();

    getElement()?.nativeElement.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  }, 0);
}
