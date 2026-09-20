import { afterEach, describe, expect, it, vi } from 'vitest'
import { getDataMode, HttpApiClient, MockApiClient } from './api'
import { ApiError } from './types'

describe('MockApiClient', () => {
  it('복수 인물 필터를 AND 조건으로 적용한다', async () => {
    const client = new MockApiClient()
    const result = await client.listPhotos('album-demo', { member_ids: ['m-1', 'm-3'] })

    expect(result.items.length).toBeGreaterThan(0)
    expect(result.items.every((photo) => ['m-1', 'm-3'].every((id) => photo.members.some((member) => member.member_id === id)))).toBe(true)
  })

  it('얼굴 없음과 여러 얼굴 오류를 구분한다', async () => {
    const client = new MockApiClient()

    await expect(client.uploadReference(new File(['x'], 'noface.jpg', { type: 'image/jpeg' }))).rejects.toMatchObject({ code: 'NO_FACE' })
    await expect(client.uploadReference(new File(['x'], 'multi.jpg', { type: 'image/jpeg' }))).rejects.toMatchObject({ code: 'MULTIPLE_FACES' })
  })

  it('수동 인물 변경 뒤에도 해당 연결을 보존한다', async () => {
    const client = new MockApiClient()
    const changed = await client.updatePhotoMembers('p-1', [{ member_id: 'm-4', excluded: false }])
    await client.reanalyzePhoto('p-1')
    const after = await client.getPhoto('p-1')

    expect(changed.members[0]).toMatchObject({ member_id: 'm-4', source: 'manual' })
    expect(after.members[0]).toMatchObject({ member_id: 'm-4', source: 'manual' })
  })
})

describe('data mode', () => {
  it('uses the real API by default and mock data only when explicitly requested', () => {
    window.history.replaceState({}, '', '/')
    expect(getDataMode()).toBe('api')
    window.history.replaceState({}, '', '/?data=mock')
    expect(getDataMode()).toBe('mock')
  })
})

describe('HttpApiClient', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('같은 origin의 /api와 세션 쿠키를 사용한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ pending: 0, processing: 0, done: 2, failed: 0 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await new HttpApiClient().getStatus('album-1')

    expect(fetchMock).toHaveBeenCalledWith('/api/albums/album-1/status', expect.objectContaining({ credentials: 'include' }))
  })

  it('공통 JSON 오류를 ApiError로 변환한다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'FORBIDDEN', message: '권한이 없어요.' }), { status: 403 })))

    await expect(new HttpApiClient().getAlbum('album-1')).rejects.toEqual(expect.objectContaining({ code: 'FORBIDDEN', status: 403 }))
  })

  it('사진 정렬 값을 백엔드 계약에 맞게 변환한다', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], page: 1, page_size: 50, total: 0 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await new HttpApiClient().listPhotos('album-1', { sort: 'best_desc', page: 1 })

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('sort=best_score_desc')
  })

  it('인물 제외 상태를 서버 payload에 명시한다', async () => {
    const responsePhoto = { id: 'p-1', album_id: 'a-1', filename: 'x.jpg', captured_at: null, created_at: '2026-09-20T00:00:00Z', analysis_status: 'done', analysis_error: null, provider: 'fixture', mode: 'mock', face_count: 1, shot_type: 'solo', tags: [], quality: {}, best_score: null, is_best: false, members: [] }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(responsePhoto), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await new HttpApiClient().updatePhotoMembers('p-1', [{ member_id: 'm-1', excluded: true }])

    expect(fetchMock).toHaveBeenCalledWith('/api/photos/p-1/members', expect.objectContaining({ body: JSON.stringify({ members: [{ member_id: 'm-1', excluded: true }] }) }))
  })

  it('다중 업로드의 파일별 성공과 실패를 반환한다', async () => {
    const payload = { results: [{ filename: 'ok.jpg', ok: true, photo: null, error: null }, { filename: 'bad.png', ok: false, photo: null, error: { code: 'TOO_LARGE', message: '파일이 너무 커요.' } }] }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 })))

    const result = await new HttpApiClient().uploadPhotos('album-1', [new File(['x'], 'ok.jpg')])

    expect(result.results).toEqual(payload.results)
  })
})
