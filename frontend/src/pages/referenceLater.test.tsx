import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../lib/api'
import { ReferenceRegistration } from './EntryFlow'
import { Gallery } from './Gallery'

afterEach(() => cleanup())

describe('deferred reference registration', () => {
  it('lets a member enter the album without uploading a reference photo', () => {
    const onDone = vi.fn()
    const uploadReference = vi.fn()
    render(<ReferenceRegistration client={{ uploadReference } as unknown as ApiClient} onDone={onDone} />)

    fireEvent.click(screen.getByRole('button', { name: '사진은 나중에 등록' }))

    expect(onDone).toHaveBeenCalledOnce()
    expect(uploadReference).not.toHaveBeenCalled()
  })

  it('offers reference registration later when the current member has no indexed photo', async () => {
    const onReference = vi.fn()
    const client = {
      getAlbum: vi.fn().mockResolvedValue({
        id: 'album-real', name: '강릉 여행', invite_code: 'aB9_xY-2', created_at: '2026-09-20T00:00:00Z', photo_count: 0,
        members: [{ id: 'member-real', display_name: '민지', reference_key: null, reference_indexed: false }],
      }),
      listPhotos: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0, total_pages: 1 }),
      getStatus: vi.fn().mockResolvedValue({ pending: 0, processing: 0, done: 0, failed: 0 }),
    } as unknown as ApiClient

    render(<Gallery client={client} albumId="album-real" currentMemberId="member-real" onOpen={() => {}} onCoverage={() => {}} onReference={onReference} />)

    const registerButton = await screen.findByRole('button', { name: '기준 사진 등록' })
    fireEvent.click(registerButton)
    expect(onReference).toHaveBeenCalledOnce()
  })

  it('hides the later action after the reference photo is indexed', async () => {
    const client = {
      getAlbum: vi.fn().mockResolvedValue({
        id: 'album-real', name: '강릉 여행', invite_code: 'aB9_xY-2', created_at: '2026-09-20T00:00:00Z', photo_count: 0,
        members: [{ id: 'member-real', display_name: '민지', reference_key: 'references/member-real.jpg', reference_indexed: true }],
      }),
      listPhotos: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0, total_pages: 1 }),
      getStatus: vi.fn().mockResolvedValue({ pending: 0, processing: 0, done: 0, failed: 0 }),
    } as unknown as ApiClient

    render(<Gallery client={client} albumId="album-real" currentMemberId="member-real" onOpen={() => {}} onCoverage={() => {}} onReference={() => {}} />)

    await waitFor(() => expect(client.getAlbum).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: '기준 사진 등록' })).toBeNull()
  })
})
