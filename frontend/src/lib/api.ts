import {
  ApiError,
  type Album,
  type AnalysisCounts,
  type Coverage,
  type DataMode,
  type MemberChange,
  type PageResult,
  type Photo,
  type PhotoFilters,
  type PhotoMember,
  type UploadBatchResponse,
} from './types'

export interface ReferenceResult {
  provider: string
  mode: string
  face_count: number
}

/** failed: 분석 실패분만 · unmatched: 미등록 얼굴이 남은 사진만 · all: 전체 */
export type ReanalyzeScope = 'failed' | 'unmatched' | 'all'

export interface JoinResult {
  album_id: string
  member_id: string
  invite_code?: string
  /** 기존 멤버로 다시 들어왔는지. 기준 사진 단계를 건너뛸지 판단하는 데 쓴다. */
  rejoined?: boolean
  reference_indexed?: boolean
}

export interface ApiClient {
  createAlbum(name: string, displayName: string, passcode: string): Promise<JoinResult & { invite_code: string }>
  joinAlbum(inviteCode: string, displayName: string, passcode: string): Promise<JoinResult>
  getAlbum(id: string): Promise<Album>
  uploadReference(file: File): Promise<ReferenceResult>
  listPhotos(albumId: string, filters: PhotoFilters): Promise<PageResult<Photo>>
  getPhoto(id: string): Promise<Photo>
  updatePhotoMembers(id: string, members: MemberChange[]): Promise<Photo>
  reanalyzePhoto(id: string): Promise<void>
  /** 앨범 사진을 일괄로 다시 분석한다. 사용자가 직접 눌러야 실행된다. */
  reanalyzeAlbum(albumId: string, scope?: ReanalyzeScope): Promise<AnalysisCounts>
  getStatus(albumId: string): Promise<AnalysisCounts>
  getCoverage(albumId: string): Promise<Coverage>
  uploadPhotos(albumId: string, files: File[]): Promise<UploadBatchResponse>
  downloadPhoto(id: string): Promise<void>
  downloadSelection(albumId: string, photoIds: string[], scope?: 'selection' | 'current_member'): Promise<void>
}

const API_BASE = '/api'

type PhotoResponse = Omit<Photo, 'image_url' | 'thumb_url' | 'members'> & {
  image_url?: string
  thumb_url?: string
  members: Array<Omit<PhotoMember, 'display_name'> & { display_name?: string }>
}

type PhotoPageResponse = Omit<PageResult<PhotoResponse>, 'total_pages'> & { total_pages?: number }

function normalizePhoto(photo: PhotoResponse): Photo {
  const imageUrl = photo.image_url ?? `${API_BASE}/photos/${photo.id}/download`
  return {
    ...photo,
    uncertain_face_count: photo.uncertain_face_count ?? 0,
    unregistered_face_count: photo.unregistered_face_count ?? 0,
    image_url: imageUrl,
    thumb_url: photo.thumb_url ?? imageUrl,
    members: photo.members.map((member) => ({ ...member, display_name: member.display_name ?? member.member_id })),
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: init.body instanceof FormData
        ? init.headers
        : { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError({ code: 'NETWORK_ERROR', message: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.' }, 0)
  }

  if (!response.ok) {
    let body = { code: 'UNKNOWN', message: '요청을 처리하지 못했어요.' }
    try {
      body = await response.json()
    } catch {
      // 서버가 공통 오류 형식이 아닌 응답을 보낸 경우 기본 문구를 사용한다.
    }
    throw new ApiError(body, response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export class HttpApiClient implements ApiClient {
  createAlbum(name: string, displayName: string, passcode: string) {
    return request<JoinResult & { invite_code: string }>('/albums', {
      method: 'POST', body: JSON.stringify({ name, display_name: displayName, passcode }),
    })
  }

  joinAlbum(inviteCode: string, displayName: string, passcode: string) {
    return request<JoinResult>('/albums/join', {
      method: 'POST', body: JSON.stringify({ invite_code: inviteCode, display_name: displayName, passcode }),
    })
  }

  getAlbum(id: string) { return request<Album>(`/albums/${id}`) }

  uploadReference(file: File) {
    const body = new FormData()
    body.append('file', file)
    return request<ReferenceResult>('/members/me/reference', { method: 'POST', body })
  }

  listPhotos(albumId: string, filters: PhotoFilters) {
    const params = new URLSearchParams()
    filters.member_ids?.forEach((id) => params.append('member_id', id))
    if (filters.shot_type) params.set('shot_type', filters.shot_type)
    if (filters.face_status) params.set('face_status', filters.face_status)
    if (filters.tag) params.set('tag', filters.tag)
    if (filters.only_best) params.set('only_best', 'true')
    if (filters.uploaded_by) params.set('uploaded_by', filters.uploaded_by)
    if (filters.sort) params.set('sort', {
      captured_desc: 'captured_at_desc',
      best_desc: 'best_score_desc',
    }[filters.sort])
    params.set('page', String(filters.page ?? 1))
    return request<PhotoPageResponse>(`/albums/${albumId}/photos?${params}`).then((page) => ({
      ...page,
      items: page.items.map(normalizePhoto),
      total_pages: page.total_pages ?? Math.max(1, Math.ceil(page.total / page.page_size)),
    }))
  }

  getPhoto(id: string) { return request<PhotoResponse>(`/photos/${id}`).then(normalizePhoto) }

  updatePhotoMembers(id: string, members: MemberChange[]) {
    return request<PhotoResponse>(`/photos/${id}/members`, {
      method: 'PUT', body: JSON.stringify({ members }),
    }).then(normalizePhoto)
  }

  reanalyzePhoto(id: string) { return request<void>(`/photos/${id}/reanalyze`, { method: 'POST' }) }
  reanalyzeAlbum(albumId: string, scope: ReanalyzeScope = 'failed') {
    return request<AnalysisCounts>(`/albums/${albumId}/reanalyze?scope=${scope}`, { method: 'POST' })
  }
  getStatus(albumId: string) { return request<AnalysisCounts>(`/albums/${albumId}/status`) }
  getCoverage(albumId: string) { return request<Coverage>(`/albums/${albumId}/coverage`) }

  uploadPhotos(albumId: string, files: File[]) {
    const body = new FormData()
    files.forEach((file) => body.append('files', file))
    return request<UploadBatchResponse>(`/albums/${albumId}/photos`, { method: 'POST', body }).then((batch) => ({
      results: batch.results.map((result) => ({
        ...result,
        photo: result.photo ? normalizePhoto(result.photo as PhotoResponse) : null,
      })),
    }))
  }

  async downloadPhoto(id: string) {
    const response = await fetch(`${API_BASE}/photos/${id}/download`, { credentials: 'include', redirect: 'follow' })
    if (!response.ok) throw new ApiError({ code: 'DOWNLOAD_FAILED', message: '원본을 내려받지 못했어요.' }, response.status)
    window.location.assign(response.url)
  }

  async downloadSelection(albumId: string, photoIds: string[], scope: 'selection' | 'current_member' = 'selection') {
    const response = await fetch(`${API_BASE}/albums/${albumId}/download`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, scope }),
    })
    if (!response.ok) {
      let body = { code: 'DOWNLOAD_FAILED', message: 'ZIP 파일을 만들지 못했어요.' }
      try { body = await response.json() } catch { /* 공통 JSON 오류가 아니면 기본 문구를 사용한다. */ }
      throw new ApiError(body, response.status)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = scope === 'current_member' ? 'zzik-my-photos.zip' : 'zzik-photos.zip'
    anchor.click()
    URL.revokeObjectURL(url)
  }
}

const members = [
  { id: 'm-1', display_name: '나', reference_key: 'refs/me.jpg', reference_indexed: true },
  { id: 'm-2', display_name: '유진', reference_key: 'refs/yujin.jpg', reference_indexed: true },
  { id: 'm-3', display_name: '민수', reference_key: 'refs/minsu.jpg', reference_indexed: true },
  { id: 'm-4', display_name: '지아', reference_key: null, reference_indexed: false },
]

const photoUrls = [
  'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1500534623283-312aade485b7?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1519046904884-53103b34b206?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1528127269322-539801943592?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1494783367193-149034c05e8f?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1517760444937-f6397edcbbcd?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1469474968028-56623f02e42e?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1530789253388-582c481c54b0?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=1000&q=85',
]

function makePhotos(): Photo[] {
  return photoUrls.map((url, index) => {
    const group = index % 3 !== 2
    const linked = group ? members.slice(0, index % 4 === 0 ? 3 : 2) : members.slice(index % 2, index % 2 + 1)
    const status = index === 10 ? 'processing' : index === 11 ? 'failed' : 'done'
    return {
      id: `p-${index + 1}`,
      album_id: 'album-demo',
      // 샘플에서도 올린이 필터가 동작하도록 멤버들에게 돌아가며 배정한다.
      uploader_member_id: members[index % members.length]?.id ?? 'm-1',
      filename: `jeju-day-${String(index + 1).padStart(2, '0')}.jpg`,
      image_url: url,
      thumb_url: url,
      captured_at: index === 9 ? null : new Date(Date.UTC(2026, 8, 18, 7 + index, index * 3)).toISOString(),
      created_at: new Date(Date.UTC(2026, 8, 18, 9 + index)).toISOString(),
      analysis_status: status,
      analysis_error: status === 'failed' ? '사진 분석 중 일시적인 오류가 발생했어요.' : null,
      provider: 'sample', mode: 'mock', face_count: group ? linked.length : 1,
      uncertain_face_count: 0, unregistered_face_count: 0,
      shot_type: group ? 'group' : 'solo',
      tags: index % 2 ? ['바다', '노을'] : ['제주', '여행'],
      quality: { sharpness: 82 + (index % 14), brightness: 72 + (index % 18), eyes_open_ratio: group ? .86 + (index % 3) * .05 : .98 },
      best_score: 72 + (index % 6) * 5,
      is_best: index % 4 === 0,
      burst_group_id: index < 2 ? 'burst-demo-a' : index >= 4 && index < 7 ? 'burst-demo-b' : null,
      members: linked.map((member, memberIndex) => ({
        member_id: member.id, display_name: member.display_name,
        similarity: 94.2 - memberIndex * 3.1, source: 'auto', excluded: false,
      })),
    }
  })
}

const delay = (ms = 180) => new Promise((resolve) => window.setTimeout(resolve, ms))

export class MockApiClient implements ApiClient {
  private photos = makePhotos()

  async createAlbum() { await delay(); return { album_id: 'album-demo', member_id: 'm-1', invite_code: 'JEJU26' } }
  async joinAlbum() { await delay(); return { album_id: 'album-demo', member_id: 'm-1', rejoined: false, reference_indexed: false } }

  async getAlbum(): Promise<Album> {
    await delay()
    return { id: 'album-demo', name: '우리들의 제주', invite_code: 'JEJU26', created_at: '2026-09-18T09:00:00Z', photo_count: this.photos.length, members, tags: [...new Set(this.photos.flatMap((photo) => photo.tags))].sort() }
  }

  async uploadReference(file: File): Promise<ReferenceResult> {
    await delay(500)
    if (file.name.toLowerCase().includes('noface')) throw new ApiError({ code: 'NO_FACE', message: '얼굴을 찾지 못했어요. 정면 얼굴이 선명한 사진을 골라 주세요.' }, 422)
    if (file.name.toLowerCase().includes('multi')) throw new ApiError({ code: 'MULTIPLE_FACES', message: '얼굴이 여러 개 보여요. 혼자 나온 사진을 골라 주세요.' }, 422)
    return { provider: 'sample', mode: 'mock', face_count: 1 }
  }

  async listPhotos(_albumId: string, filters: PhotoFilters): Promise<PageResult<Photo>> {
    await delay()
    let result = [...this.photos]
    if (filters.member_ids?.length) result = result.filter((photo) => filters.member_ids!.every((id) => photo.members.some((member) => member.member_id === id && !member.excluded)))
    if (filters.shot_type) result = result.filter((photo) => photo.shot_type === filters.shot_type)
    if (filters.face_status === 'unregistered') result = result.filter((photo) => Boolean(photo.unregistered_face_count))
    if (filters.face_status === 'uncertain') result = result.filter((photo) => Boolean(photo.uncertain_face_count))
    if (filters.face_status === 'no_face') result = result.filter((photo) => photo.shot_type === 'no_face')
    if (filters.tag) result = result.filter((photo) => photo.tags.includes(filters.tag!))
    if (filters.only_best) result = result.filter((photo) => photo.is_best)
    if (filters.uploaded_by === 'others') result = result.filter((photo) => photo.uploader_member_id !== 'm-1')
    if (filters.uploaded_by === 'me') result = result.filter((photo) => photo.uploader_member_id === 'm-1')
    if (filters.sort === 'best_desc') result.sort((a, b) => (b.best_score ?? 0) - (a.best_score ?? 0))
    const page = filters.page ?? 1
    const pageSize = 8
    return { items: result.slice((page - 1) * pageSize, page * pageSize), page, page_size: pageSize, total: result.length, total_pages: Math.max(1, Math.ceil(result.length / pageSize)) }
  }

  async getPhoto(id: string) {
    await delay()
    const photo = this.photos.find((item) => item.id === id)
    if (!photo) throw new ApiError({ code: 'NOT_FOUND', message: '사진을 찾지 못했어요.' }, 404)
    return structuredClone(photo)
  }

  async updatePhotoMembers(id: string, changes: MemberChange[]) {
    const photo = this.photos.find((item) => item.id === id)
    if (!photo) throw new ApiError({ code: 'NOT_FOUND', message: '사진을 찾지 못했어요.' }, 404)
    photo.members = changes.map((change) => {
      const previous = photo.members.find((item) => item.member_id === change.member_id)
      const member = members.find((item) => item.id === change.member_id)!
      return { ...(previous ?? { member_id: change.member_id, display_name: member.display_name, similarity: null }), source: 'manual', excluded: change.excluded }
    })
    await delay()
    return structuredClone(photo)
  }

  async reanalyzePhoto(id: string) {
    const photo = this.photos.find((item) => item.id === id)
    if (!photo) throw new ApiError({ code: 'NOT_FOUND', message: '사진을 찾지 못했어요.' }, 404)
    photo.analysis_status = 'processing'
    photo.analysis_error = null
    await delay(350)
  }

  async getStatus(): Promise<AnalysisCounts> {
    await delay(80)
    return this.photos.reduce<AnalysisCounts>((counts, photo) => ({ ...counts, [photo.analysis_status]: counts[photo.analysis_status] + 1 }), { pending: 0, processing: 0, done: 0, failed: 0 })
  }

  async reanalyzeAlbum(_albumId: string, scope: ReanalyzeScope = 'failed'): Promise<AnalysisCounts> {
    this.photos
      .filter((photo) => scope === 'all'
        || (scope === 'failed' && photo.analysis_status === 'failed')
        || (scope === 'unmatched' && photo.analysis_status === 'done' && (photo.unregistered_face_count ?? 0) > 0))
      .forEach((photo) => { photo.analysis_status = 'processing'; photo.analysis_error = null })
    await delay(350)
    return this.getStatus()
  }

  async getCoverage(): Promise<Coverage> {
    await delay()
    return { total: this.photos.length, members: members.map((member) => ({ member_id: member.id, display_name: member.display_name, photo_count: this.photos.filter((photo) => photo.members.some((item) => item.member_id === member.id && !item.excluded)).length })) }
  }

  async uploadPhotos(_albumId: string, files: File[]): Promise<UploadBatchResponse> {
    await delay(Math.min(1000, files.length * 100))
    return { results: files.map((file) => ({ filename: file.name, ok: true, photo: null, error: null })) }
  }
  async downloadPhoto() { await delay(); window.alert('샘플 모드에서는 원본 다운로드를 실행하지 않아요.') }
  async downloadSelection() { await delay(); window.alert('샘플 모드에서는 ZIP 다운로드를 실행하지 않아요.') }
}

export function getDataMode(): DataMode {
  return new URLSearchParams(window.location.search).get('data') === 'mock' ? 'mock' : 'api'
}

export function createApiClient(mode: DataMode): ApiClient {
  return mode === 'api' ? new HttpApiClient() : new MockApiClient()
}
