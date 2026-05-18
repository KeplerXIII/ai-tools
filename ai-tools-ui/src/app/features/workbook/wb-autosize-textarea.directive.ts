import {
  AfterViewInit,
  Directive,
  ElementRef,
  HostListener,
  Input,
  OnChanges,
} from '@angular/core';

@Directive({
  selector: 'textarea[appWbAutosize]',
  standalone: true,
})
export class WbAutosizeTextareaDirective implements AfterViewInit, OnChanges {
  @Input() appWbAutosizeMinRows = 2;
  @Input() appWbAutosizeMaxRows = 16;

  constructor(private readonly el: ElementRef<HTMLTextAreaElement>) {}

  ngAfterViewInit(): void {
    this.resize();
  }

  ngOnChanges(): void {
    queueMicrotask(() => this.resize());
  }

  @HostListener('input')
  onInput(): void {
    this.resize();
  }

  resize(): void {
    const el = this.el.nativeElement;
    const style = getComputedStyle(el);
    const lineHeight = Number.parseFloat(style.lineHeight) || 21;
    const padY = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
    const borderY =
      Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth);
    const minH = lineHeight * this.appWbAutosizeMinRows + padY + borderY;
    const maxH = lineHeight * this.appWbAutosizeMaxRows + padY + borderY;

    el.style.height = '0';
    el.style.overflow = 'hidden';
    const height = Math.min(maxH, Math.max(minH, el.scrollHeight));
    el.style.height = `${height}px`;
    el.style.overflowY = height >= maxH - 1 ? 'auto' : 'hidden';
  }
}
