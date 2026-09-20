import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>
const base = { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

export const LogoMarkIcon = (props: IconProps) => <svg viewBox="0 0 48 48" aria-hidden="true" {...props}>
  <path d="M11.5 32C7 34.8 2.2 33 2 28.6c-.2-4.8 4.1-7.6 7.5-5.2" fill="none" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round" />
  <ellipse cx="20.5" cy="30" rx="13.8" ry="11.5" fill="currentColor" />
  <circle cx="34" cy="14" r="8.2" fill="currentColor" />
  <circle cx="34" cy="14" r="4.6" fill="#ffd0c9" />
  <path fill="currentColor" d="M26 25.5C27.3 18.7 32.1 15 38.2 15c4.5 0 7.5 3.6 7.5 7.6 0 .9-.1 1.8-.4 2.6l2.2 1.5c.6.4.6 1.3-.1 1.6l-2.9 1.3c-1.7 5.2-6.5 8.9-12.1 8.9-4.7 0-8.4-3.2-8.4-7.3 0-2 .7-3.7 2-5.2Z" />
  <circle cx="39" cy="21.5" r="1.7" fill="#6a3934" />
  <circle cx="39.5" cy="21" r=".55" fill="white" />
  <circle cx="46.3" cy="27.2" r="1.45" fill="#f64f73" />
  <path d="m42.4 29.1 5 1.8m-5.7.2 4.6 3" fill="none" stroke="#a94239" strokeWidth="1.15" strokeLinecap="round" />
  <ellipse cx="16.8" cy="40.4" rx="3.2" ry="1.5" fill="#e85b49" />
  <ellipse cx="31.5" cy="39.8" rx="3" ry="1.45" fill="#e85b49" />
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
