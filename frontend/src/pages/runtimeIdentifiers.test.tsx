import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../lib/api'
import { Landing } from './EntryFlow'
import { Gallery } from './Gallery'

afterEach(() => cleanup())

describe('runtime album identifiers', () => {
  it('passes the joined album and member IDs into the app flow', async () => {
    const joinAlbum = vi.fn().mockResolvedValue({ album_id: 'album-real', member_id: 'member-real' })
    const onComplete = vi.fn()
    render(<Landing client={{ joinAlbum } as unknown as ApiClient} onComplete={onComplete} onPreview={() => {}} />)

    fireEvent.change(screen.getByLabelText('초대 코드'), { target: { value: 'trip26' } })
    fireEvent.change(screen.getByLabelText('내 이름'), { target: { value: '민지' } })
    fireEvent.click(screen.getByRole('button', { name: /앨범 들어가기/ }))

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      albumId: 'album-real', memberId: 'member-real', displayName: '민지',
    }))
    expect(joinAlbum).toHaveBeenCalledWith('TRIP26', '민지')
  })

  it('uses runtime IDs for album requests and the mine filter', async () => {
    const client = {
      getAlbum: vi.fn().mockResolvedValue({ id: 'album-real', name: '부산', invite_code: 'BUSAN1', created_at: '2026-09-20T00:00:00Z', photo_count: 0, members: [] }),
      listPhotos: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0, total_pages: 1 }),
      getStatus: vi.fn().mockResolvedValue({ pending: 0, processing: 0, done: 0, failed: 0 }),
    } as unknown as ApiClient

    render(<Gallery client={client} albumId="album-real" currentMemberId="member-real" onOpen={() => {}} onCoverage={() => {}} />)
    await waitFor(() => expect(client.listPhotos).toHaveBeenCalledWith('album-real', expect.objectContaining({ member_ids: [] })))

    fireEvent.click(screen.getByRole('tab', { name: '내 사진' }))
    await waitFor(() => expect(client.listPhotos).toHaveBeenLastCalledWith('album-real', expect.objectContaining({ member_ids: ['member-real'] })))
  })
})
