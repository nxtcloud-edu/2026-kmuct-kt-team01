import { useState } from 'react'
import './InviteCode.css'

function copySelectedText(code: string) {
  const temporary = document.createElement('textarea')
  temporary.value = code
  temporary.setAttribute('readonly', '')
  temporary.style.position = 'fixed'
  temporary.style.opacity = '0'
  temporary.style.pointerEvents = 'none'
  document.body.appendChild(temporary)
  temporary.focus()
  temporary.select()
  temporary.setSelectionRange(0, code.length)

  let copied = false
  try { copied = document.execCommand?.('copy') ?? false } catch { copied = false }
  temporary.remove()
  return copied
}

export function InviteCodeCopyButton({ code }: { code: string }) {
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
      } catch { /* Browser permissions may require the synchronous fallback. */ }
    }

    if (!copied) copied = copySelectedText(code)
    setMessage(copied ? '초대코드를 복사했어요.' : '자동 복사가 안 돼요. 초대코드를 직접 선택해 복사해 주세요.')
    setCopying(false)
  }

  return <span className="invite-code-copy">
    <button type="button" aria-label="초대코드 복사" title="초대코드 복사" onClick={() => void copy()} disabled={copying}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>
    </button>
    <span className="invite-code-copy__status" role="status">{message}</span>
  </span>
}
