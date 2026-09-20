import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../lib/api'
import type { Album, Coverage, Photo } from '../lib/types'
import { ErrorState, Spinner } from '../components/AsyncState'
import { ChartIcon, DownloadIcon } from '../components/icons'
import EditorPanel from '../editor/EditorPanel'

const albumId = 'album-demo'

export function PhotoDetail({ client, photoId, onBack }: { client: ApiClient; photoId: string; onBack: () => void }) {
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [album, setAlbum] = useState<Album | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [editingPeople, setEditingPeople] = useState(false)
  const [memberIds, setMemberIds] = useState<string[]>([])
  const load = useCallback(async () => {
    setError(null)
    try { const [photoResult, albumResult] = await Promise.all([client.getPhoto(photoId), client.getAlbum(albumId)]); setPhoto(photoResult); setAlbum(albumResult); setMemberIds(photoResult.members.filter((member) => !member.excluded).map((member) => member.member_id)) }
    catch (caught) { setError(caught) }
  }, [client, photoId])
  useEffect(() => { void load() }, [load])
  async function saveMembers() { try { setPhoto(await client.updatePhotoMembers(photoId, album?.members.map((member) => ({ member_id: member.id, excluded: !memberIds.includes(member.id) })) ?? [])); setEditingPeople(false) } catch (caught) { setError(caught) } }
  async function reanalyze() { try { await client.reanalyzePhoto(photoId); await load() } catch (caught) { setError(caught) } }
  if (error) return <main className="page-shell detail-state"><ErrorState error={error} onRetry={() => void load()} /><button className="preview-link" onClick={onBack}>앨범으로 돌아가기</button></main>
  if (!photo || !album) return <main className="page-shell detail-state"><Spinner label="사진을 불러오는 중" /></main>

  return <main className="photo-detail page-shell">
    <button className="back-button" onClick={onBack}>‹ <span>앨범으로</span></button>
    <div className="detail-layout"><section className="detail-image"><img src={photo.image_url} alt={photo.filename} /><div className="image-actions"><span>{photo.filename}</span><button onClick={() => void client.downloadPhoto(photo.id)}><DownloadIcon />원본 다운로드</button></div></section>
      <aside className="detail-info"><div className="detail-title"><div><span className="eyebrow">PHOTO DETAILS</span><h1>{photo.captured_at ? new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(photo.captured_at)) : '촬영 정보 없음'}</h1></div><span className={`status-pill ${photo.analysis_status}`}>{photo.analysis_status === 'done' ? '분석 완료' : photo.analysis_status === 'failed' ? '분석 실패' : '분석 중'}</span></div>
        <section className="info-section"><div className="section-title"><h2>등장 인물 <span>{memberIds.length}</span></h2><button onClick={() => setEditingPeople(!editingPeople)}>{editingPeople ? '취소' : '수정'}</button></div>{editingPeople ? <div className="member-editor">{album.members.map((member, index) => <label key={member.id}><input type="checkbox" checked={memberIds.includes(member.id)} onChange={() => setMemberIds((ids) => ids.includes(member.id) ? ids.filter((id) => id !== member.id) : [...ids, member.id])} /><span className={`avatar color-${index}`}>{member.display_name[0]}</span>{member.display_name}</label>)}<button className="button primary full" onClick={() => void saveMembers()}>변경 저장</button></div> : <div className="people-list">{photo.members.filter((member) => !member.excluded).map((member, index) => <span key={member.member_id}><i className={`avatar color-${index}`}>{member.display_name[0]}</i><b>{member.display_name}</b><small>{member.source === 'manual' ? '직접 지정' : member.similarity ? `${member.similarity.toFixed(1)}% 일치` : '자동 분석'}</small></span>)}</div>}</section>
        <section className="info-section"><div className="section-title"><h2>사진 품질</h2><span>{photo.face_count}명 · {photo.shot_type === 'group' ? '단체샷' : photo.shot_type === 'solo' ? '개인 사진' : '인물 없음'}</span></div><div className="quality-grid">{([['선명도', photo.quality.sharpness], ['밝기', photo.quality.brightness], ['눈 뜬 비율', photo.quality.eyes_open_ratio ? photo.quality.eyes_open_ratio * 100 : undefined]] as const).map(([label, value]) => <div key={label}><span>{label}</span><b>{value === undefined ? '정보 없음' : `${Math.round(value)}%`}</b><i><em style={{ width: `${value ?? 0}%` }} /></i></div>)}</div></section>
        <section className="info-section analysis-info"><div><span>분석 방식</span><b>{photo.provider ?? '미분석'} · {photo.mode ?? '정보 없음'}</b></div>{photo.analysis_status === 'failed' && <button className="button secondary" onClick={() => void reanalyze()}>분석 다시 시도</button>}</section>
      </aside></div>
    <div className="editor-panel-shell">
      <EditorPanel
        photoId={photo.id}
        originalUrl={photo.image_url}
        members={album.members.map(({ id, display_name }) => ({ id, display_name }))}
        onSaved={() => { void load() }}
      />
    </div>
  </main>
}

export function CoverageDashboard({ client, onBack }: { client: ApiClient; onBack: () => void }) {
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => client.getCoverage(albumId).then(setCoverage).catch(setError), [client])
  useEffect(() => { void load() }, [load])
  return <main className="coverage-page page-shell"><button className="back-button" onClick={onBack}>‹ <span>앨범으로</span></button><div className="coverage-heading"><span className="eyebrow">NO ONE LEFT BEHIND</span><h1>사진 누락 현황</h1><p>모든 멤버가 여행 사진을 빠짐없이 받았는지 확인하세요.</p></div>{error ? <ErrorState error={error} onRetry={() => void load()} /> : !coverage ? <Spinner /> : <><section className="coverage-total"><span><ChartIcon /></span><div><small>앨범 전체 사진</small><b>{coverage.total}<em>장</em></b></div><p>인물 분석 결과를 기준으로 집계했어요.</p></section><section className="coverage-list"><div className="coverage-list-head"><h2>멤버별 사진</h2><span>전체 {coverage.total}장 기준</span></div>{coverage.members.map((member, index) => { const rate = coverage.total ? Math.round(member.photo_count / coverage.total * 100) : 0; return <article key={member.member_id}><span className={`avatar color-${index}`}>{member.display_name[0]}</span><div><div><b>{member.display_name}</b><span>{member.photo_count}장 · {rate}%</span></div><i><em style={{ width: `${rate}%` }} /></i></div>{member.photo_count === 0 && <strong>확인 필요</strong>}</article> })}</section></>}</main>
}
