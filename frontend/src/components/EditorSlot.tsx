import type { Member, Photo } from '../lib/types'
import { SparkleIcon } from './icons'

/** 5번 역할의 편집·승인 컴포넌트가 구현해야 할 공개 props 계약. */
export interface EditorPanelProps {
  photo: Photo
  currentMemberId: string
  albumMembers: Member[]
  onVersionChanged: () => void | Promise<void>
}

export function EditorSlot({ photo }: EditorPanelProps) {
  return (
    <section className="editor-slot" aria-label="사진 보정">
      <div className="editor-slot-icon"><SparkleIcon /></div>
      <div>
        <span className="eyebrow">EDIT & APPROVE</span>
        <h3>보정과 멤버 승인이 연결될 자리예요</h3>
        <p>사진 ID <code>{photo.id}</code>를 기준으로 5번 역할의 편집 패널을 이 영역에 끼웁니다.</p>
      </div>
      <span className="status-pill muted">연결 대기</span>
    </section>
  )
}
