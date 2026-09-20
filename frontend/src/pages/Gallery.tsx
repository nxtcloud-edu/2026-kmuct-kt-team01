import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ApiClient } from '../lib/api'
import type { Album, AnalysisCounts, Photo, PhotoFilters } from '../lib/types'
import { EmptyState, ErrorState, Spinner } from '../components/AsyncState'
import { CheckIcon, DownloadIcon, SparkleIcon, UploadIcon } from '../components/icons'

type GalleryTab = 'all' | 'mine' | 'group' | 'best'
const albumId = 'album-demo'
const currentMemberId = 'm-1'

function ProgressBanner({ counts }: { counts: AnalysisCounts }) {
  const total = counts.pending + counts.processing + counts.done + counts.failed
  const percent = total ? Math.round((counts.done / total) * 100) : 0
  return <section className="progress-banner"><span className="progress-icon"><SparkleIcon /></span><div className="progress-content"><div><b>{counts.pending + counts.processing > 0 ? '사진을 분석하고 있어요' : '사진 분석이 끝났어요'}</b><span>{counts.done}/{total} 완료{counts.failed > 0 && ` · ${counts.failed}장 재시도 필요`}</span></div><div className="progress-track"><i style={{ width: `${percent}%` }} /></div></div><strong>{percent}%</strong></section>
}

function PhotoCard({ photo, selectable, selected, onSelect, onOpen }: { photo: Photo; selectable: boolean; selected: boolean; onSelect: () => void; onOpen: () => void }) {
  return <button className={`photo-card ${selected ? 'selected' : ''}`} onClick={selectable ? onSelect : onOpen} aria-label={`${photo.filename}${selected ? ', 선택됨' : ''}`}><img src={photo.thumb_url} alt="" loading="lazy" /><span className="photo-shade" />{selectable && <span className="select-check">{selected && <CheckIcon />}</span>}{photo.is_best && <span className="best-badge"><SparkleIcon />BEST</span>}{photo.analysis_status !== 'done' && <span className={`analysis-badge ${photo.analysis_status}`}>{photo.analysis_status === 'failed' ? '분석 실패' : '분석 중'}</span>}<span className="photo-meta"><span>{photo.members.slice(0, 3).map((member) => member.display_name).join(' · ') || '인물 없음'}</span><b>{photo.best_score ? `${Math.round(photo.best_score)}점` : ''}</b></span></button>
}

export function Gallery({ client, onOpen, onCoverage }: { client: ApiClient; onOpen: (id: string) => void; onCoverage: () => void }) {
  const uploadRef = useRef<HTMLInputElement>(null)
  const [album, setAlbum] = useState<Album | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [counts, setCounts] = useState<AnalysisCounts>({ pending: 0, processing: 0, done: 0, failed: 0 })
  const [tab, setTab] = useState<GalleryTab>('all')
  const [memberIds, setMemberIds] = useState<string[]>([])
  const [tag, setTag] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [uploading, setUploading] = useState(false)

  const filters = useMemo<PhotoFilters>(() => ({ page, member_ids: tab === 'mine' ? [...new Set([currentMemberId, ...memberIds])] : memberIds, shot_type: tab === 'group' ? 'group' : undefined, only_best: tab === 'best' || undefined, sort: tab === 'best' ? 'best_desc' : 'captured_desc', tag: tag || undefined }), [page, tab, memberIds, tag])
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { const [albumResult, photoResult, statusResult] = await Promise.all([client.getAlbum(albumId), client.listPhotos(albumId, filters), client.getStatus(albumId)]); setAlbum(albumResult); setPhotos(photoResult.items); setTotal(photoResult.total); setTotalPages(photoResult.total_pages); setCounts(statusResult) }
    catch (caught) { setError(caught) } finally { setLoading(false) }
  }, [client, filters])

  useEffect(() => { void load() }, [load])
  useEffect(() => { const timer = window.setInterval(() => { void client.getStatus(albumId).then(setCounts).catch(() => undefined) }, 2000); return () => window.clearInterval(timer) }, [client])

  function changeTab(next: GalleryTab) { setTab(next); setPage(1); setSelected([]) }
  function toggleMember(id: string) { setMemberIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); setPage(1) }
  async function upload(files: FileList | null) { if (!files?.length) return; setUploading(true); try { await client.uploadPhotos(albumId, Array.from(files)); await load() } catch (caught) { setError(caught) } finally { setUploading(false) } }
  async function downloadSelected() { try { await client.downloadSelection(albumId, selected) } catch (caught) { setError(caught) } }

  return <main className="album-page page-shell">
    <section className="album-heading"><div><span className="eyebrow">SHARED ALBUM · {album?.invite_code ?? '······'}</span><h1>{album?.name ?? '앨범'}</h1><p>{album?.members.length ?? 0}명이 함께한 여행 · 사진 {album?.photo_count ?? 0}장</p></div><div className="album-actions"><button className="button ghost" onClick={onCoverage}>누락 현황</button><button className="button primary" onClick={() => uploadRef.current?.click()} disabled={uploading}><UploadIcon />{uploading ? '올리는 중…' : '사진 올리기'}</button><input ref={uploadRef} type="file" accept="image/jpeg,image/png" multiple hidden onChange={(event) => void upload(event.target.files)} /></div></section>
    <ProgressBanner counts={counts} />
    <div className="gallery-toolbar"><div className="gallery-tabs" role="tablist">{([['all', '전체'], ['mine', '내 사진'], ['group', '단체샷'], ['best', '베스트컷']] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => changeTab(key)}>{key === 'best' && <SparkleIcon />}{label}</button>)}</div><button className={`select-mode ${selecting ? 'active' : ''}`} onClick={() => { setSelecting(!selecting); setSelected([]) }}>{selecting ? '선택 취소' : '사진 선택'}</button></div>
    <div className="filters"><span>함께 나온 사람</span><div className="chip-row">{album?.members.map((member, index) => <button key={member.id} className={`person-chip ${memberIds.includes(member.id) ? 'active' : ''}`} onClick={() => toggleMember(member.id)}><span className={`avatar color-${index}`}>{member.display_name.slice(0, 1)}</span>{member.display_name}{memberIds.includes(member.id) && <CheckIcon />}</button>)}</div><span className="filter-divider" /><div className="chip-row">{['', '바다', '제주', '노을'].map((item) => <button key={item || 'all'} className={`tag-chip ${tag === item ? 'active' : ''}`} onClick={() => { setTag(item); setPage(1) }}>{item || '모든 태그'}</button>)}</div></div>
    {error ? <ErrorState error={error} onRetry={() => void load()} /> : loading ? <Spinner label="추억을 불러오는 중" /> : photos.length === 0 ? <EmptyState title="조건에 맞는 사진이 없어요" description="선택한 사람이나 태그를 바꿔보세요." action={<button className="button secondary" onClick={() => { setMemberIds([]); setTag(''); changeTab('all') }}>필터 초기화</button>} /> : <><div className="gallery-summary"><span>사진 <b>{total}</b>장</span><small>{memberIds.length > 1 && '선택한 사람이 모두 나온 사진만 표시해요 · '}최근 촬영순</small></div><div className="photo-grid">{photos.map((photo) => <PhotoCard key={photo.id} photo={photo} selectable={selecting} selected={selected.includes(photo.id)} onSelect={() => setSelected((items) => items.includes(photo.id) ? items.filter((id) => id !== photo.id) : [...items, photo.id])} onOpen={() => onOpen(photo.id)} />)}</div><nav className="pagination" aria-label="사진 페이지"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>이전</button>{Array.from({ length: totalPages }, (_, index) => index + 1).map((value) => <button key={value} className={page === value ? 'active' : ''} onClick={() => setPage(value)}>{value}</button>)}<button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>다음</button></nav></>}
    {selecting && selected.length > 0 && <div className="selection-bar"><span><b>{selected.length}장</b> 선택됨</span><button className="button light" onClick={() => void downloadSelected()}><DownloadIcon />ZIP으로 받기</button></div>}
  </main>
}
