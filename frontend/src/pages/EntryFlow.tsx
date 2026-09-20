import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { ApiClient } from '../lib/api'
import { ApiError, type ActiveAlbum } from '../lib/types'
import { ArrowIcon, CameraIcon, CheckIcon, SparkleIcon, UsersIcon } from '../components/icons'

export function Landing({ client, onComplete, onPreview }: { client: ApiClient; onComplete: (album: ActiveAlbum) => void; onPreview: () => void }) {
  const [form, setForm] = useState<'join' | 'create'>('join')
  const [name, setName] = useState('')
  const [albumName, setAlbumName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!name.trim() || (form === 'join' ? !inviteCode.trim() : !albumName.trim())) {
      setError('입력하지 않은 항목이 있어요.')
      return
    }
    setLoading(true)
    try {
      const displayName = name.trim()
      const result = form === 'join'
        ? await client.joinAlbum(inviteCode.trim(), displayName)
        : await client.createAlbum(albumName.trim(), displayName)
      const code = 'invite_code' in result && typeof result.invite_code === 'string' ? result.invite_code : undefined
      onComplete({ albumId: result.album_id, memberId: result.member_id, displayName, ...(code ? { inviteCode: code } : {}) })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '요청을 처리하지 못했어요.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="landing">
      <section className="hero-copy">
        <div className="eyebrow"><span className="eyebrow-dot" />TRAVEL PHOTO, TOGETHER</div>
        <h1>여행의 모든 순간,<br /><em>모두의 최애컷</em>으로.</h1>
        <p>사진을 한곳에 모으면 찍이 인물과 장면을 알아서 정리해요.<br className="desktop-only" /> 잘 나온 단체 사진을 고르고 함께 승인해 간직하세요.</p>
        <div className="hero-points"><span><i><UsersIcon /></i>내 사진 자동 분류</span><span><i><SparkleIcon /></i>베스트컷 추천</span><span><i><CheckIcon /></i>모두 함께 승인</span></div>
      </section>
      <section className="entry-card">
        <div className="entry-tabs" role="tablist">
          <button role="tab" aria-selected={form === 'join'} className={form === 'join' ? 'active' : ''} onClick={() => setForm('join')}>앨범 참여</button>
          <button role="tab" aria-selected={form === 'create'} className={form === 'create' ? 'active' : ''} onClick={() => setForm('create')}>새 앨범</button>
        </div>
        <form onSubmit={submit}>
          <div className="form-heading"><span className="camera-mark"><CameraIcon /></span><div><h2>{form === 'join' ? '초대받은 앨범이 있나요?' : '새로운 여행을 시작할까요?'}</h2><p>{form === 'join' ? '친구에게 받은 초대 코드를 입력하세요.' : '여행 이름과 내 이름만 있으면 준비 끝!'}</p></div></div>
          {form === 'join' ? <label>초대 코드<input aria-label="초대 코드" value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="받은 코드를 그대로 붙여넣으세요" /><small>대소문자를 구분해요.</small></label> : <label>앨범 이름<input value={albumName} onChange={(event) => setAlbumName(event.target.value)} placeholder="예: 우리들의 제주" /></label>}
          <label>내 이름<input value={name} onChange={(event) => setName(event.target.value)} placeholder="앨범에 표시될 이름" /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button primary full" disabled={loading}>{loading ? '잠시만요…' : form === 'join' ? '앨범 들어가기' : '앨범 만들기'}<ArrowIcon /></button>
          <button type="button" className="preview-link" onClick={onPreview}>샘플 흐름 먼저 둘러보기</button>
        </form>
      </section>
      <div className="hero-orb orb-one" /><div className="hero-orb orb-two" />
    </main>
  )
}

export function ReferenceRegistration({ client, onDone }: { client: ApiClient; onDone: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  function pick(selected?: File) {
    if (!selected) return
    if (preview) URL.revokeObjectURL(preview)
    setFile(selected); setPreview(URL.createObjectURL(selected)); setError(null)
  }
  async function upload() {
    if (!file) return inputRef.current?.click()
    setLoading(true); setError(null)
    try { await client.uploadReference(file); onDone() }
    catch (caught) {
      const apiError = caught instanceof ApiError ? caught : null
      setError({ code: apiError?.code ?? 'UPLOAD_FAILED', message: apiError?.message ?? '사진을 등록하지 못했어요.' })
    } finally { setLoading(false) }
  }

  return (
    <main className="onboarding page-shell">
      <div className="stepper"><span className="done"><CheckIcon /></span><i /><span className="active">2</span><i /><span>3</span></div>
      <div className="onboarding-heading"><span className="eyebrow">JUST ONE SELFIE</span><h1>내 사진을 찾아드릴게요</h1><p>혼자 나온 정면 사진 한 장이면 충분해요.<br />찍이 앨범 속 내 사진만 모아 보여줄게요.</p></div>
      <div className="reference-layout">
        <button className={`reference-preview ${preview ? 'has-image' : ''}`} onClick={() => inputRef.current?.click()}>{preview ? <img src={preview} alt="선택한 기준 얼굴" /> : <><span><CameraIcon /></span><strong>사진을 선택해 주세요</strong><small>카메라 또는 앨범에서 선택</small></>}{preview && <span className="change-photo">사진 바꾸기</span>}</button>
        <div className="reference-guide"><h2>이런 사진이 좋아요</h2><ul><li><CheckIcon /><span><b>정면을 바라본 얼굴</b><small>얼굴 전체가 또렷하게 보여야 해요.</small></span></li><li><CheckIcon /><span><b>혼자 나온 사진</b><small>여러 명이 함께 나온 사진은 피해주세요.</small></span></li><li><CheckIcon /><span><b>밝고 선명한 사진</b><small>모자나 선글라스는 잠시 벗어주세요.</small></span></li></ul>
          {error && <div className="inline-error" role="alert"><b>{error.code === 'NO_FACE' ? '얼굴을 찾지 못했어요' : error.code === 'MULTIPLE_FACES' ? '얼굴이 여러 개 보여요' : error.code === 'INVALID_IMAGE' ? '사진을 읽지 못했어요' : error.code === 'UNSUPPORTED_MEDIA_TYPE' ? 'JPEG 또는 PNG가 필요해요' : error.code === 'FILE_TOO_LARGE' ? '사진 용량이 너무 커요' : '등록하지 못했어요'}</b><span>{error.message}</span><small>오류 코드 {error.code}</small></div>}
          <input ref={inputRef} type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" capture="user" hidden onChange={(event) => pick(event.target.files?.[0])} />
          <button className="button primary full" onClick={upload} disabled={loading}>{loading ? '얼굴을 확인하고 있어요…' : file ? '이 사진으로 등록' : '사진 선택하기'}<CameraIcon /></button>
          <button type="button" className="button ghost full reference-later" onClick={onDone} disabled={loading}>사진은 나중에 등록</button>
          <p className="privacy-note">등록 사진은 앨범 속 인물을 찾는 데만 사용돼요.</p>
        </div>
      </div>
    </main>
  )
}
