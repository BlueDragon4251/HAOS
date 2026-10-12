import { cn } from '../lib/cn.ts'

/** HAOS identity. Keep the component's historical export name for source compatibility. */
export function HeraldLogo({ height = 14, className }: { height?: number; className?: string }) {
  return (
    <svg viewBox="0 0 96 96" height={height} width={height} role="img" aria-label="HAOS" draggable={false} className={cn('shrink-0 select-none', className)}>
      <defs><linearGradient id="haos-shell-mark" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#6ae5ff" /><stop offset="1" stopColor="#5180ff" /></linearGradient></defs>
      <path d="M48 6 83 26v44L48 90 13 70V26z" fill="#0c1a33" stroke="url(#haos-shell-mark)" strokeWidth="6" strokeLinejoin="round" />
      <path d="M29 31v34m38-34v34M29 48h38" stroke="url(#haos-shell-mark)" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="48" cy="14" r="4" fill="#b3f7ff" />
    </svg>
  )
}
