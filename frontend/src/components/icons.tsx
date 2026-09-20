import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>
const base = { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

export const LogoMarkIcon = (props: IconProps) => <svg viewBox="0 0 48 48" aria-hidden="true" {...props}>
  <path d="M10 34.5C4 36 1.5 32 3.5 27.5 4.5 25 6.5 24 8.5 25" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" />
  <circle cx="34" cy="12" r="7.5" fill="currentColor" />
  <path fill="currentColor" d="M9 38.5C6.5 34 6.8 28.5 9.5 24 13 18.5 19 15.5 26 15.5 28.5 10.5 34 8.5 39 11.5 42 13.5 43 17 42 20l4 3-4.5 3C39.5 34.5 32.5 40.5 23.5 40.5H12c-1.3 0-2.3-.7-3-2Z" />
  <circle cx="34" cy="12" r="3.5" fill="#e85b49" />
  <circle cx="38.5" cy="19" r="1.5" fill="white" />
  <circle cx="45.1" cy="23.1" r="1" fill="#6a3934" />
</svg>
export const CameraIcon = (props: IconProps) => <svg {...base} {...props}><path d="M14.5 5 13 3h-2L9.5 5H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z"/><circle cx="12" cy="12.5" r="4"/></svg>
export const UploadIcon = (props: IconProps) => <svg {...base} {...props}><path d="m12 16 0-11m-4 4 4-4 4 4"/><path d="M5 15v4h14v-4"/></svg>
export const UsersIcon = (props: IconProps) => <svg {...base} {...props}><circle cx="9" cy="8" r="3"/><path d="M3.5 19v-2a5.5 5.5 0 0 1 11 0v2M16 5.2a3 3 0 0 1 0 5.6M17 13a5 5 0 0 1 3.5 4.8V19"/></svg>
export const GridIcon = (props: IconProps) => <svg {...base} {...props}><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
export const ChartIcon = (props: IconProps) => <svg {...base} {...props}><path d="M4 20V10m6 10V4m6 16v-7m5 7H2"/></svg>
export const ArrowIcon = (props: IconProps) => <svg {...base} {...props}><path d="m9 18 6-6-6-6"/></svg>
export const DownloadIcon = (props: IconProps) => <svg {...base} {...props}><path d="M12 3v12m-4-4 4 4 4-4M5 20h14"/></svg>
export const CheckIcon = (props: IconProps) => <svg {...base} {...props}><path d="m5 12 4 4L19 6"/></svg>
export const SparkleIcon = (props: IconProps) => <svg {...base} {...props}><path d="m12 3 1.3 4.2L17 9l-3.7 1.8L12 15l-1.3-4.2L7 9l3.7-1.8zM5 15l.7 2.3L8 18l-2.3.7L5 21l-.7-2.3L2 18l2.3-.7zM19 3l.6 1.4L21 5l-1.4.6L19 7l-.6-1.4L17 5l1.4-.6z"/></svg>
