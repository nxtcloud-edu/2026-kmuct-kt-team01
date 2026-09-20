import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpApiClient, MockApiClient } from './api'
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
    const changed = await client.updatePhotoMembers('p-1', ['m-4'])
    await client.reanalyzePhoto('p-1')
    const after = await client.getPhoto('p-1')

    expect(changed.members[0]).toMatchObject({ member_id: 'm-4', source: 'manual' })
    expect(after.members[0]).toMatchObject({ member_id: 'm-4', source: 'manual' })
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
})
