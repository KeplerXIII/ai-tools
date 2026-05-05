import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  Input,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { catchError, of, take } from 'rxjs';

@Component({
  selector: 'app-svg-icon',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './svg-icon.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SvgIconComponent implements OnChanges {
  @Input() public class = '';
  @Input() public name: string | null | undefined = null;
  @Input() public src: string | null | undefined = null;

  public svg: SafeHtml = '';

  private static cache = new Map<string, SafeHtml>();

  private requestToken = 0;

  constructor(
    private readonly http: HttpClient,
    private readonly sanitizer: DomSanitizer,
    private readonly cdr: ChangeDetectorRef
  ) {}

  public ngOnChanges(changes: SimpleChanges): void {
    if (!changes['src'] && !changes['name']) return;
    this.render();
  }

  private render(): void {
    const src = this.src ?? null;
    const name = this.name ?? null;

    if (src) {
      const cached = SvgIconComponent.cache.get(src);
      if (cached) {
        this.svg = cached;
        this.cdr.markForCheck();
        return;
      }

      const token = ++this.requestToken;

      this.http
        .get(src, { responseType: 'text' })
        .pipe(
          take(1),
          catchError(() => of(''))
        )
        .subscribe(raw => {
          if (token !== this.requestToken) return;

          const safe = raw ? this.sanitizer.bypassSecurityTrustHtml(raw) : '';

          SvgIconComponent.cache.set(src, safe);

          this.svg = safe;
          this.cdr.markForCheck();
        });

      return;
    }

    this.svg = '';
    this.cdr.markForCheck();
  }
}
