import { useId, useRef, useState } from 'react'
import './InviteCode.css'

export function InviteCode({ code }: { code: string }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState('')
  const [copying, setCopying] = useState(false)

  async function copy() {
    setCopying(true)
    setMessage('')
    let copied = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code)
        copied = true
      }
    } catch { /* HTTP or browser permissions may require the selection fallback. */ }
    if (!copied) {
      input.current?.focus()
      input.current?.select()
      input.current?.setSelectionRange(0, code.length)
      try { copied = document.execCommand?.('copy') ?? false } catch { copied = false }
    }
    setMessage(copied ? '초대코드를 복사했어요. 친구에게 보내주세요.' : '자동 복사가 안 돼요. 위 코드를 길게 누르거나 Ctrl+C로 직접 복사해 주세요.')
    setCopying(false)
  }

  return <section className="invite-code" aria-label="친구 초대">
    <div className="invite-code__controls">
      <label htmlFor={id}>초대코드</label>
      <input id={id} aria-label="앨범 초대 코드" ref={input} readOnly value={code} spellCheck={false} onClick={(event) => event.currentTarget.select()} />
      <button type="button" className="button secondary" aria-label="초대코드 복사" onClick={() => void copy()} disabled={copying}>{copying ? '복사 중' : '복사'}</button>
    </div>
    <p className="invite-code__status" role="status">{message}</p>
  </section>
}
