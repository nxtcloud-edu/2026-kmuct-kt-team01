import type { ReactNode } from 'react'
import { ApiError } from '../lib/types'

export function Spinner({ label = '불러오는 중' }: { label?: string }) {
  return <div className="state-card" role="status"><span className="spinner" aria-hidden="true" /><p>{label}</p></div>
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="state-card"><span className="state-icon" aria-hidden="true">◇</span><h3>{title}</h3><p>{description}</p>{action}</div>
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null
  const forbidden = apiError?.status === 401 || apiError?.status === 403
  return (
    <div className="state-card error-state" role="alert">
      <span className="state-icon" aria-hidden="true">!</span>
      <h3>{forbidden ? '이 앨범을 볼 권한이 없어요' : '잠시 연결이 끊겼어요'}</h3>
      <p>{apiError?.message ?? '네트워크 상태를 확인하고 다시 시도해 주세요.'}</p>
      {onRetry && <button className="button secondary" onClick={onRetry}>다시 시도</button>}
    </div>
  )
}
