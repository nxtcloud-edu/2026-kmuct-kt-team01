import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ApiClient, ReanalyzeScope } from '../lib/api'
import type { Album, AnalysisCounts, Photo, PhotoFilters, UploadBatchResponse } from '../lib/types'
import { EmptyState, ErrorState, Spinner } from '../components/AsyncState'
import { CameraIcon, CheckIcon, CloseIcon, DownloadIcon, LayersIcon, SparkleIcon, UploadIcon } from '../components/icons'
import { InviteCodeCopyButton } from '../components/InviteCode'

type GalleryTab = 'all' | 'mine' | 'group' | 'best'
type FaceStatus = '' | 'unregistered' | 'uncertain' | 'no_face'
type UploadedBy = '' | 'me' | 'others'
type GridItem = Photo | Photo[]

function ProgressBanner({ counts, onReanalyze, busy }: { counts: AnalysisCounts; onReanalyze?: (scope: ReanalyzeScope) => void; busy?: boolean }) {
  const total = counts.pending + counts.processing + counts.done + counts.failed
  const percent = total ? Math.round((counts.done / total) * 100) : 0
  return <section className="progress-banner"><span className="progress-icon"><SparkleIcon /></span><div className="progress-content"><div><b>{counts.pending + counts.processing > 0 ? '사진을 분석하고 있어요' : '사진 분석이 끝났어요'}</b><span>{counts.done}/{total} 완료{counts.failed > 0 && ` · ${counts.failed}장 재시도 필요`}</span></div><div className="progress-track"><i style={{ width: `${percent}%` }} /></div></div><strong>{percent}%</strong>{onReanalyze && total > 0 && <span className="progress-actions">{counts.failed > 0 && <button className="button secondary" onClick={() => onReanalyze('failed')} disabled={busy}>실패 {counts.failed}장 다시 분석</button>}<button className="button ghost" onClick={() => onReanalyze('all')} disabled={busy}>전체 다시 분석</button></span>}</section>
}

function peopleLabel(photo: Photo): string {
  return photo.shot_type === 'no_face'
    ? '사람 없는 사진'
    : [photo.members.slice(0, 3).map((member) => member.display_name).join(' · '), photo.uncertain_face_count ? `확인 필요 ${photo.uncertain_face_count}` : '', photo.unregistered_face_count ? `미등록 인물 ${photo.unregistered_face_count}` : ''].filter(Boolean).join(' · ') || '인물 확인 필요'

}

// burst_group_id가 같은 사진(연속 컷·중복)을 한 장의 '스택' 카드로 묶는다. 대표 컷은
// best_score가 가장 높은 사진 — 그래야 스택 표지가 실제로 제일 잘 나온 컷이 된다.
function groupForDisplay(photos: Photo[]): GridItem[] {
  const byGroup = new Map<string, Photo[]>()
  for (const photo of photos) {
    if (!photo.burst_group_id) continue
    const list = byGroup.get(photo.burst_group_id) ?? []
    list.push(photo)
    byGroup.set(photo.burst_group_id, list)
  }
  const placed = new Set<string>()
  const items: GridItem[] = []
  for (const photo of photos) {
    const groupId = photo.burst_group_id
    const group = groupId ? byGroup.get(groupId) : undefined
    if (groupId && group && group.length > 1) {
      if (placed.has(groupId)) continue
      placed.add(groupId)
      items.push([...group].sort((a, b) => (b.best_score ?? 0) - (a.best_score ?? 0)))
    } else {
      items.push(photo)
    }
  }
  return items
}

function PhotoCard({ photo, selectable, selected, onSelect, onOpen }: { photo: Photo; selectable: boolean; selected: boolean; onSelect: () => void; onOpen: () => void }) {
  return <button className={`photo-card ${selected ? 'selected' : ''}`} onClick={selectable ? onSelect : onOpen} aria-label={`${photo.filename}${selected ? ', 선택됨' : ''}`}><img src={photo.thumb_url} alt="" loading="lazy" /><span className="photo-shade" />{selectable && <span className="select-check">{selected && <CheckIcon />}</span>}{photo.is_best && <span className="best-badge"><SparkleIcon />BEST</span>}{photo.mode === 'mock' && <span className="analysis-badge">샘플 분석</span>}{photo.mode === 'hybrid' && <span className="analysis-badge">AI 분류</span>}{photo.analysis_status !== 'done' && <span className={`analysis-badge ${photo.analysis_status}`}>{photo.analysis_status === 'failed' ? '분석 실패' : '분석 중'}</span>}<span className="photo-meta"><span>{peopleLabel(photo)}</span></span></button>
}

function PhotoStack({ photos, selectable, selected, onSelect, onOpen }: { photos: Photo[]; selectable: boolean; selected: boolean; onSelect: () => void; onOpen: () => void }) {
  const cover = photos[0]
  if (!cover) return null
  return <button className={`photo-card photo-stack ${selected ? 'selected' : ''}`} onClick={selectable ? onSelect : onOpen} aria-label={`${peopleLabel(cover)}, 비슷한 사진 ${photos.length}장`}>
    <span className="stack-layer stack-layer-2" /><span className="stack-layer stack-layer-1" />
    <img src={cover.thumb_url} alt="" loading="lazy" /><span className="photo-shade" />
    {selectable && <span className="select-check">{selected && <CheckIcon />}</span>}
    <span className="stack-count"><LayersIcon />{photos.length}</span>
    {cover.is_best && <span className="best-badge"><SparkleIcon />BEST</span>}
    {cover.mode === 'mock' && <span className="analysis-badge">샘플 분석</span>}
    {cover.mode === 'hybrid' && <span className="analysis-badge">AI 분류</span>}
    <span className="photo-meta"><span>{peopleLabel(cover)}</span></span>
  </button>
}

function StackViewer({ photos, onClose, onOpen }: { photos: Photo[]; onClose: () => void; onOpen: (id: string) => void }) {
  return <div className="stack-viewer" role="dialog" aria-label="비슷한 사진 모아보기" onClick={onClose}>
    <div className="stack-viewer-panel" onClick={(event) => event.stopPropagation()}>
      <div className="stack-viewer-head"><b>비슷한 사진 {photos.length}장</b><button className="icon-button" onClick={onClose} aria-label="닫기"><CloseIcon /></button></div>
      <div className="stack-viewer-grid">{photos.map((photo) => <button key={photo.id} className="stack-viewer-item" onClick={() => onOpen(photo.id)}><img src={photo.thumb_url} alt="" />{photo.is_best && <span className="best-badge"><SparkleIcon />BEST</span>}</button>)}</div>
    </div>
  </div>
}

export function Gallery({ client, albumId, currentMemberId, onOpen, onCoverage, onReference }: { client: ApiClient; albumId: string; currentMemberId: string; onOpen: (id: string) => void; onCoverage: () => void; onReference?: () => void }) {
  const uploadRef = useRef<HTMLInputElement>(null)
  const [album, setAlbum] = useState<Album | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [counts, setCounts] = useState<AnalysisCounts>({ pending: 0, processing: 0, done: 0, failed: 0 })
  const [tab, setTab] = useState<GalleryTab>('all')
  const [memberId, setMemberId] = useState<string | null>(null)
  const [faceStatus, setFaceStatus] = useState<FaceStatus>('')
  const [tag, setTag] = useState('')
  const [uploadedBy, setUploadedBy] = useState<UploadedBy>('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [stackOpen, setStackOpen] = useState<Photo[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [uploading, setUploading] = useState(false)
  const [downloadingMine, setDownloadingMine] = useState(false)
  const [uploadReport, setUploadReport] = useState<UploadBatchResponse | null>(null)
  const [rematching, setRematching] = useState(false)
  const [rematchNotice, setRematchNotice] = useState<string | null>(null)

  const filters = useMemo<PhotoFilters>(() => ({ page, member_ids: tab === 'mine' ? [...new Set([currentMemberId, ...(memberId ? [memberId] : [])])] : (memberId ? [memberId] : []), shot_type: tab === 'group' ? 'group' : undefined, face_status: faceStatus || undefined, only_best: tab === 'best' || undefined, sort: tab === 'best' ? 'best_desc' : 'captured_desc', tag: tag || undefined, uploaded_by: uploadedBy || undefined }), [page, tab, memberId, faceStatus, tag, uploadedBy, currentMemberId])
  const gridItems = useMemo(() => groupForDisplay(photos), [photos])
  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true); setError(null)
    try { const [albumResult, photoResult, statusResult] = await Promise.all([client.getAlbum(albumId), client.listPhotos(albumId, filters), client.getStatus(albumId)]); setAlbum(albumResult); setPhotos(photoResult.items); setTotal(photoResult.total); setTotalPages(photoResult.total_pages); setCounts(statusResult) }
    catch (caught) { setError(caught) } finally { if (showLoading) setLoading(false) }
  }, [client, albumId, filters])

  useEffect(() => { void load() }, [load])
  useEffect(() => { const timer = window.setInterval(() => { if (counts.pending + counts.processing > 0) void load(false); else void client.getStatus(albumId).then(setCounts).catch(() => undefined) }, 2000); return () => window.clearInterval(timer) }, [client, albumId, counts.pending, counts.processing, load])

  function changeTab(next: GalleryTab) { setTab(next); if (faceStatus === 'no_face' && next !== 'all') setFaceStatus(''); setPage(1); setSelected([]) }
  function selectMember(id: string) { setMemberId((current) => current === id ? null : id); setPage(1) }
  function changeFaceStatus(next: FaceStatus) { setFaceStatus(next); if (next === 'no_face') { setTab('all'); setMemberId(null) } setPage(1) }
  function toggleSelected(id: string) { setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]) }
  function toggleStackSelected(ids: string[]) { setSelected((items) => ids.every((id) => items.includes(id)) ? items.filter((id) => !ids.includes(id)) : [...new Set([...items, ...ids])]) }
  async function upload(files: FileList | null) { if (!files?.length) return; setUploading(true); setUploadReport(null); try { setUploadReport(await client.uploadPhotos(albumId, Array.from(files))); await load() } catch (caught) { setError(caught) } finally { setUploading(false) } }
  async function reanalyze(scope: ReanalyzeScope) {
    if (scope === 'all' && !window.confirm('앨범의 모든 사진을 다시 분석할까요? 직접 지정한 인물은 유지되지만 보정본 승인은 초기화돼요.')) return
    setRematching(true); setRematchNotice(null)
    try {
      const next = await client.reanalyzeAlbum(albumId, scope)
      setCounts(next)
      const queued = next.pending + next.processing
      setRematchNotice(queued > 0
        ? `${queued}장을 다시 분석하고 있어요.`
        : scope === 'unmatched' ? '다시 분류할 사진이 없어요.' : '다시 분석할 사진이 없어요.')
      await load(false)
    } catch (caught) { setError(caught) } finally { setRematching(false) }
  }
  async function downloadSelected() { try { await client.downloadSelection(albumId, selected) } catch (caught) { setError(caught) } }
  async function downloadMine() { setDownloadingMine(true); try { await client.downloadSelection(albumId, [], 'current_member') } catch (caught) { setError(caught) } finally { setDownloadingMine(false) } }
  function openStackOrPhoto(id: string) { setStackOpen(null); onOpen(id) }

  return <main className="album-page page-shell">
    <section className="album-heading"><div><span className="eyebrow">SHARED ALBUM · {album?.invite_code ?? '······'}{album && <InviteCodeCopyButton code={album.invite_code} />}</span><h1>{album?.name ?? '앨범'}</h1><p>{album?.members.length ?? 0}명이 함께한 여행 · 사진 {album?.photo_count ?? 0}장</p></div><div className="album-actions">{onReference && album?.members.some((member) => member.id === currentMemberId && !member.reference_indexed) && <button className="button ghost reference-register" onClick={onReference} aria-label="기준 사진 등록"><CameraIcon />기준 사진 등록</button>}{album?.members.some((member) => member.id === currentMemberId && member.reference_indexed) && <button className="button ghost rematch-faces" onClick={() => void reanalyze('unmatched')} disabled={rematching} aria-label={rematching ? '다시 분류 중' : '내 얼굴로 다시 분류'}><SparkleIcon />{rematching ? '다시 분류 중…' : '내 얼굴로 다시 분류'}</button>}<button className="button ghost" onClick={onCoverage}>누락 현황</button><button className="button secondary my-photos-download" onClick={() => void downloadMine()} disabled={downloadingMine} aria-label={downloadingMine ? '내 사진 준비 중' : '내 사진 받기'}><DownloadIcon />{downloadingMine ? '준비 중…' : '내 사진 받기'}</button><button className="button primary" onClick={() => uploadRef.current?.click()} disabled={uploading}><UploadIcon />{uploading ? '올리는 중…' : '사진 올리기'}</button><input ref={uploadRef} type="file" accept="image/jpeg,image/png,image/heic,image/heif,.jpg,.jpeg,.png,.heic,.heif" multiple hidden onChange={(event) => void upload(event.target.files)} /></div></section>
    {uploadReport && <div className={`upload-report ${uploadReport.results.some((result) => !result.ok) ? 'has-errors' : ''}`} role="status"><b>{uploadReport.results.filter((result) => result.ok).length}장 업로드 완료</b>{uploadReport.results.some((result) => !result.ok) && <span>실패: {uploadReport.results.filter((result) => !result.ok).map((result) => result.filename).join(', ')}</span>}<button onClick={() => setUploadReport(null)} aria-label="업로드 결과 닫기">×</button></div>}
    {rematchNotice && <div className="upload-report" role="status"><b>{rematchNotice}</b><span>다시 분석한 사진은 보정본 승인이 초기화돼요.</span><button onClick={() => setRematchNotice(null)} aria-label="다시 분석 안내 닫기">×</button></div>}
    <ProgressBanner counts={counts} onReanalyze={(scope) => void reanalyze(scope)} busy={rematching} />
    {photos.some((photo) => photo.mode === 'mock') && <div className="mock-analysis-notice" role="note"><b>현재 로컬에서는 샘플 분석 결과를 표시하고 있어요.</b><span>얼굴 이름과 태그는 합성 결과입니다. 실제 얼굴별 분류는 AWS Rekognition 연결 후 정확해집니다.</span></div>}
    {photos.some((photo) => photo.mode === 'hybrid') && <div className="mock-analysis-notice" role="note"><b>장면 태그는 외부 AI가 분류했어요.</b><span>인물 이름과 사진 품질 점수는 얼굴 인식 엔진의 결과를 그대로 씁니다.</span></div>}
    <div className="gallery-toolbar"><div className="gallery-tabs" role="tablist">{([['all', '전체'], ['mine', '내 사진'], ['group', '단체샷'], ['best', '베스트컷']] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => changeTab(key)}>{key === 'best' && <SparkleIcon />}{label}</button>)}</div><button className={`select-mode ${selecting ? 'active' : ''}`} onClick={() => { setSelecting(!selecting); setSelected([]) }}>{selecting ? '선택 취소' : '사진 선택'}</button></div>
    <section className="filter-panel" aria-label="사진 분류 필터">
      <div className="filter-row"><span className="filter-label">얼굴별</span><div className="chip-row">{album?.members.map((member, index) => <button key={member.id} className={`person-chip ${memberId === member.id ? 'active' : ''}`} onClick={() => selectMember(member.id)}><span className={`avatar color-${index}`}>{member.display_name.slice(0, 1)}</span>{member.display_name}{memberId === member.id && <CheckIcon />}</button>)}</div><div className="chip-row face-status-chips">{([['', '얼굴 전체'], ['unregistered', '미등록 인물'], ['uncertain', '확인 필요'], ['no_face', '사람 없음']] as const).map(([value, label]) => <button key={value || 'all-faces'} className={`status-chip ${faceStatus === value ? 'active' : ''}`} onClick={() => changeFaceStatus(value)}>{label}</button>)}</div></div>
      <div className="filter-row"><span className="filter-label">태그별</span><div className="chip-row">{['', ...(album?.tags ?? [])].map((item) => <button key={item || 'all-tags'} className={`tag-chip ${tag === item ? 'active' : ''}`} onClick={() => { setTag(item); setPage(1) }}>{item || '모든 태그'}</button>)}{album?.tags?.length === 0 && <span className="filter-empty">분석된 태그가 없어요</span>}</div></div>
      <div className="filter-row"><span className="filter-label">올린이</span><div className="chip-row">{([['', '모두'], ['others', '다른 사람이 올린 사진'], ['me', '내가 올린 사진']] as const).map(([value, label]) => <button key={value || 'all-uploaders'} className={`status-chip ${uploadedBy === value ? 'active' : ''}`} onClick={() => { setUploadedBy(value); setPage(1); setSelected([]) }}>{label}</button>)}</div></div>
    </section>
    {error ? <ErrorState error={error} onRetry={() => void load()} /> : loading ? <Spinner label="추억을 불러오는 중" /> : photos.length === 0 ? <EmptyState title="조건에 맞는 사진이 없어요" description="선택한 얼굴 상태나 태그를 바꿔보세요." action={<button className="button secondary" onClick={() => { setMemberId(null); setFaceStatus(''); setTag(''); setUploadedBy(''); changeTab('all') }}>필터 초기화</button>} /> : <><div className="gallery-summary"><span>사진 <b>{total}</b>장</span><small>최근 촬영순</small></div><div className="photo-grid">{gridItems.map((item) => Array.isArray(item)
      ? <PhotoStack key={item[0]?.id ?? Math.random()} photos={item} selectable={selecting} selected={item.every((photo) => selected.includes(photo.id))} onSelect={() => toggleStackSelected(item.map((photo) => photo.id))} onOpen={() => setStackOpen(item)} />
      : <PhotoCard key={item.id} photo={item} selectable={selecting} selected={selected.includes(item.id)} onSelect={() => toggleSelected(item.id)} onOpen={() => onOpen(item.id)} />
    )}</div><nav className="pagination" aria-label="사진 페이지"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>이전</button>{Array.from({ length: totalPages }, (_, index) => index + 1).map((value) => <button key={value} className={page === value ? 'active' : ''} onClick={() => setPage(value)}>{value}</button>)}<button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>다음</button></nav></>}
    {selecting && selected.length > 0 && <div className="selection-bar"><span><b>{selected.length}장</b> 선택됨</span><button className="button light" onClick={() => void downloadSelected()}><DownloadIcon />ZIP으로 받기</button></div>}
    {stackOpen && <StackViewer photos={stackOpen} onClose={() => setStackOpen(null)} onOpen={openStackOrPhoto} />}
  </main>
}
