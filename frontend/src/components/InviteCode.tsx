import { useId, useRef, useState, type RefObject } from 'react'
import './InviteCode.css'

function copySelectedText(code: string, input?: HTMLInputElement | null) {
  let temporary: HTMLTextAreaElement | null = null
  const target = input ?? (() => {
    temporary = document.createElement('textarea')
    temporary.value = code
    temporary.setAttribute('readonly', '')
    temporary.style.position = 'fixed'
    temporary.style.opacity = '0'
    temporary.style.pointerEvents = 'none'
    document.body.appendChild(temporary)
    return temporary
  })()

  target.focus()
  target.select()
  target.setSelectionRange(0, code.length)

  let copied = false
  try { copied = document.execCommand?.('copy') ?? false } catch { copied = false }
  temporary?.remove()
  return copied
}

function useInviteCodeCopy(code: string, input?: RefObject<HTMLInputElement | null>) {
  const [message, setMessage] = useState('')
  const [copying, setCopying] = useState(false)

  async function copy() {
    setCopying(true)
    setMessage('')
    let copied = false

    if (window.isSecureContext && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(code)
        copied = true
      } catch { /* Browser permissions may require the selection fallback. */ }
    }

    if (!copied) copied = copySelectedText(code, input?.current)

    setMessage(copied ? '초대코드를 복사했어요. 친구에게 보내주세요.' : '자동 복사가 안 돼요. 선택된 코드를 길게 누르거나 Ctrl+C로 직접 복사해 주세요.')
    setCopying(false)
  }

  return { copy, copying, message }
}

export function InviteCode({ code }: { code: string }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const { copy, copying, message } = useInviteCodeCopy(code, input)

  return <section className="invite-code" aria-label="친구 초대">
    <div className="invite-code__controls">
      <label htmlFor={id}>초대코드</label>
      <input id={id} aria-label="앨범 초대 코드" ref={input} readOnly value={code} spellCheck={false} onFocus={(event) => event.currentTarget.select()} onClick={(event) => event.currentTarget.select()} />
      <button type="button" className="button secondary" aria-label="초대코드 복사" onClick={() => void copy()} disabled={copying}>{copying ? '복사 중' : '복사'}</button>
    </div>
    <p className="invite-code__status" role="status">{message}</p>
  </section>
}

export function InviteCodeCopyButton({ code }: { code: string }) {
  const { copy, copying, message } = useInviteCodeCopy(code)

  return <span className="invite-code-copy">
    <button type="button" aria-label="초대코드 복사" title="초대코드 복사" onClick={() => void copy()} disabled={copying}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>
    </button>
    <span className="invite-code-copy__status" role="status">{message}</span>
  </span>
}
