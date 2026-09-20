import { useEffect, useId, useRef, useState } from 'react'
import './EditorPanel.css'

export interface EditorMember { id: string; display_name: string }

export interface EditVersion {
  id: string
  photo_id: string
  author_member_id: string
  parent_id: string | null
  number: number
  created_at: string
  brightness: number
  saturation: number
  approval_count: number
  required_count: number
  is_final: boolean
  can_approve: boolean
  approved_by_me: boolean
  approval_blocked_reason: string | null
  provider: string | null
  mode: string | null
  storage_mode: string
}

export interface EditorPanelProps {
  photoId: string
  originalUrl: string
  members: EditorMember[]
  onSaved: () => void
}

async function request<T>(path: string, signal: AbortSignal, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init, signal, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.message === 'string' ? body.message : '요청을 처리하지 못했어요. 다시 시도해 주세요.')
  if (body === null) throw new Error('서버 응답을 확인할 수 없어요.')
  return body as T
}

const isUuid = (value: string) => /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value)
const messageOf = (error: unknown) => error instanceof Error ? error.message : '연결을 확인하고 다시 시도해 주세요.'

// The key cancels previous photo requests and resets unsaved state on navigation.
export default function EditorPanel(props: EditorPanelProps) {
  return <EditorBody key={props.photoId} {...props} />
}

function EditorBody({ photoId, originalUrl, members, onSaved }: EditorPanelProps) {
  const id = useId()
  const [brightness, setBrightness] = useState(1)
  const [saturation, setSaturation] = useState(1)
  const [parentId, setParentId] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)
  const [versions, setVersions] = useState<EditVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const lifecycle = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const revision = useRef(0)
  const refreshVersions = useRef<() => void>(() => {})
  const memberSignature = members.map((member) => member.id).sort().join(',')
  const sample = !isUuid(photoId)

  useEffect(() => {
    const controller = new AbortController()
    lifecycle.current = controller
    if (sample) { setLoading(false); return () => controller.abort() }
    let refreshing = false
    const refresh = () => {
      if (refreshing || busy.current || controller.signal.aborted) return
      refreshing = true
      const startedAtRevision = revision.current
      request<{ versions: EditVersion[] }>(`/photos/${photoId}/edits`, controller.signal)
        .then((result) => {
          if (controller.signal.aborted || startedAtRevision !== revision.current) return
          if (!Array.isArray(result.versions)) throw new Error('보정 기록 응답을 확인할 수 없어요.')
          setVersions(result.versions)
          setLoadFailed(false)
          setError('')
        })
        .catch((failure: unknown) => {
          if (!controller.signal.aborted && startedAtRevision === revision.current) {
            setError(messageOf(failure)); setLoadFailed(true)
          }
        })
        .finally(() => { refreshing = false; if (!controller.signal.aborted) setLoading(false) })
    }
    refreshVersions.current = refresh
    refresh()
    const refreshVisible = () => { if (!document.hidden) refresh() }
    const interval = window.setInterval(refreshVisible, 10_000)
    window.addEventListener('focus', refreshVisible)
    document.addEventListener('visibilitychange', refreshVisible)
    return () => {
      controller.abort()
      window.clearInterval(interval)
      window.removeEventListener('focus', refreshVisible)
      document.removeEventListener('visibilitychange', refreshVisible)
    }
  }, [photoId, sample])

  useEffect(() => { refreshVersions.current() }, [memberSignature])

  const disabled = loading || pending || sample || loadFailed

  async function mutate(action: (signal: AbortSignal) => Promise<void>) {
    const controller = lifecycle.current
    if (disabled || busy.current || !controller || controller.signal.aborted) return
    busy.current = true
    revision.current += 1
    setPending(true)
    setError('')
    setNotice('')
    try { await action(controller.signal) }
    catch (failure) { if (!controller.signal.aborted) setError(messageOf(failure)) }
    finally {
      busy.current = false
      if (!controller.signal.aborted) setPending(false)
    }
  }

  function save() {
    void mutate(async (signal) => {
      const saved = await request<EditVersion>(`/photos/${photoId}/edits`, signal, {
        method: 'POST', body: JSON.stringify({ brightness, saturation, parent_id: parentId }),
      })
      if (signal.aborted) return
      setVersions((previous) => [saved, ...previous.filter((version) => version.id !== saved.id)])
      setParentId(saved.id)
      setNotice(`버전 ${saved.number}을 저장했어요.`)
      onSaved()
    })
  }

  function approve(version: EditVersion) {
    void mutate(async (signal) => {
      await request<EditVersion>(`/edits/${version.id}/approve`, signal, { method: version.approved_by_me ? 'DELETE' : 'POST' })
      if (signal.aborted) return
      // More than one version can change its final flag; refresh the entire list.
      try {
        const result = await request<{ versions: EditVersion[] }>(`/photos/${photoId}/edits`, signal)
        if (signal.aborted) return
        setVersions(result.versions)
        setNotice(version.approved_by_me ? '승인을 취소했어요.' : '승인했어요.')
        onSaved()
      } catch (failure) {
        if (signal.aborted) return
        setLoadFailed(true)
        throw new Error(`승인 변경은 처리됐지만 목록을 새로 불러오지 못했어요. ${messageOf(failure)}`)
      }
    })
  }

  return <section className="zzik-editor" aria-label="사진 보정" aria-busy={loading || pending}>
    <header className="zzik-editor__header">
      <div><span className="zzik-editor__eyebrow">EDIT TOGETHER</span><h2>함께 고르는 한 장</h2></div>
      <button type="button" disabled={disabled} onClick={() => { setBrightness(1); setSaturation(1); setComparing(false) }}>초기화</button>
    </header>

    <div className="zzik-editor__preview">
      <img src={originalUrl} alt="보정 미리보기" draggable={false}
        style={{ filter: comparing ? 'none' : `brightness(${brightness}) saturate(${saturation})` }} />
      <span className="zzik-editor__preview-label">{comparing ? '원본' : '빠른 미리보기'}</span>
    </div>
    <div className="zzik-editor__compare">
      <p>저장본과 미리보기의 색감이 다를 수 있어요.</p>
      <button type="button" aria-pressed={comparing} aria-label="누르는 동안 원본 보기"
        onPointerDown={(event) => { event.currentTarget.setPointerCapture?.(event.pointerId); setComparing(true) }}
        onPointerUp={() => setComparing(false)} onPointerCancel={() => setComparing(false)}
        onLostPointerCapture={() => setComparing(false)} onBlur={() => setComparing(false)}
        onKeyDown={(event) => { if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); setComparing(true) } }}
        onKeyUp={(event) => { if (event.key === ' ' || event.key === 'Enter') setComparing(false) }}>
        꾹 눌러 원본 보기
      </button>
    </div>

    <fieldset disabled={disabled} className="zzik-editor__controls">
      <legend className="zzik-editor__sr-only">밝기와 채도 조절</legend>
      <div className="zzik-editor__slider">
        <div className="zzik-editor__slider-heading"><label htmlFor={`${id}-brightness`}>밝기</label><output htmlFor={`${id}-brightness`}>{brightness.toFixed(2)}</output></div>
        <input id={`${id}-brightness`} type="range" min="0.5" max="1.5" step="0.01" value={brightness} onChange={(event) => setBrightness(Number(event.target.value))} />
      </div>
      <div className="zzik-editor__slider">
        <div className="zzik-editor__slider-heading"><label htmlFor={`${id}-saturation`}>채도</label><output htmlFor={`${id}-saturation`}>{saturation.toFixed(2)}</output></div>
        <input id={`${id}-saturation`} type="range" min="0" max="2" step="0.01" value={saturation} onChange={(event) => setSaturation(Number(event.target.value))} />
      </div>
    </fieldset>

    {sample && <p className="zzik-editor__message">샘플 사진에서는 보정 저장과 승인을 실행하지 않아요.</p>}
    {error && <p role="alert" className="zzik-editor__error">{error}</p>}
    <p role="status" className="zzik-editor__status">{notice || (loading ? '버전을 불러오는 중…' : pending ? '처리하는 중…' : '')}</p>
    <button className="zzik-editor__save" type="button" disabled={disabled} onClick={save}>{pending ? '처리 중…' : '새 버전 저장'}</button>

    <div className="zzik-editor__versions">
      <h3>보정 기록 <span>{versions.length}</span></h3>
      <button type="button" disabled={pending || loading || sample} onClick={() => refreshVersions.current()}>목록 새로고침</button>
      {loadFailed && <p className="zzik-editor__message">최신 승인 상태를 확인할 수 없어요. 목록을 새로 불러와 주세요.</p>}
      {!loading && !loadFailed && versions.length === 0 && <p className="zzik-editor__empty">아직 저장된 보정 버전이 없어요.</p>}
      <ol>{versions.map((version) => <li key={version.id} className={parentId === version.id ? 'is-selected' : ''}>
        <button type="button" className="zzik-editor__version" disabled={disabled} aria-pressed={parentId === version.id}
          aria-label={`버전 ${version.number} 선택`} onClick={() => { setParentId(version.id); setBrightness(version.brightness); setSaturation(version.saturation) }}>
          <strong>버전 {version.number} {version.is_final && !loadFailed && <span className="zzik-editor__final">최종본</span>}</strong>
          <span>{members.find((member) => member.id === version.author_member_id)?.display_name ?? '탈퇴한 멤버'}</span>
          <time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString('ko-KR')}</time>
        </button>
        <div className="zzik-editor__approval">
          <span>승인 {version.approval_count} / {version.required_count}</span>
          {(version.can_approve || version.approved_by_me) && <button type="button" disabled={disabled} aria-label={`버전 ${version.number} ${version.approved_by_me ? '승인 취소' : '승인'}`} onClick={() => approve(version)}>{version.approved_by_me ? '승인 취소' : '승인'}</button>}
          {version.approval_blocked_reason && <span>등장 인물 확인이 필요해요.</span>}
          {version.storage_mode === 'fixture' && <span className="zzik-editor__sample">테스트 저장소</span>}
          {version.mode === 'mock' && <span className="zzik-editor__sample">샘플 분석</span>}
        </div>
      </li>)}</ol>
    </div>
  </section>
}
