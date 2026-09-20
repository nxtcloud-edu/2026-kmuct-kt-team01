import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '../lib/api'
import { Landing } from './EntryFlow'
import { Gallery } from './Gallery'
import { PhotoDetail } from './PhotoDetail'

afterEach(() => cleanup())

describe('runtime album identifiers', () => {
  it('retains the new album invitation for immediate sharing', async () => {
    const createAlbum = vi.fn().mockResolvedValue({ album_id: 'album-real', member_id: 'owner', invite_code: 'aB9_xY-2' })
    const onComplete = vi.fn()
    render(<Landing client={{ createAlbum } as unknown as ApiClient} onComplete={onComplete} onPreview={() => {}} />)
    fireEvent.click(screen.getByRole('tab', { name: '새 앨범' }))
    fireEvent.change(screen.getByLabelText('앨범 이름'), { target: { value: '여행' } })
    fireEvent.change(screen.getByLabelText('내 이름'), { target: { value: '민지' } })
    fireEvent.click(screen.getByRole('button', { name: /앨범 만들기/ }))
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({ albumId: 'album-real', memberId: 'owner', displayName: '민지', inviteCode: 'aB9_xY-2' }))
  })
  it('passes the joined album and member IDs into the app flow', async () => {
    const joinAlbum = vi.fn().mockResolvedValue({ album_id: 'album-real', member_id: 'member-real' })
    const onComplete = vi.fn()
    render(<Landing client={{ joinAlbum } as unknown as ApiClient} onComplete={onComplete} onPreview={() => {}} />)

    fireEvent.change(screen.getByLabelText('초대 코드'), { target: { value: '  aB9_xY-2  ' } })
    fireEvent.change(screen.getByLabelText('내 이름'), { target: { value: '민지' } })
    fireEvent.click(screen.getByRole('button', { name: /앨범 들어가기/ }))

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      albumId: 'album-real', memberId: 'member-real', displayName: '민지',
    }))
    expect(joinAlbum).toHaveBeenCalledWith('aB9_xY-2', '민지')
  })

  it('uses runtime IDs for album requests and the mine filter', async () => {
    const client = {
      getAlbum: vi.fn().mockResolvedValue({ id: 'album-real', name: '부산', invite_code: 'BUSAN1', created_at: '2026-09-20T00:00:00Z', photo_count: 0, members: [] }),
      listPhotos: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0, total_pages: 1 }),
      getStatus: vi.fn().mockResolvedValue({ pending: 0, processing: 0, done: 0, failed: 0 }),
    } as unknown as ApiClient

    render(<Gallery client={client} albumId="album-real" currentMemberId="member-real" onOpen={() => {}} onCoverage={() => {}} />)
    await waitFor(() => expect(client.listPhotos).toHaveBeenCalledWith('album-real', expect.objectContaining({ member_ids: [] })))
    expect(screen.getByText(/SHARED ALBUM · BUSAN1/)).toBeTruthy()
    expect(screen.queryByLabelText('앨범 초대 코드')).toBeNull()
    expect(screen.getByRole('button', { name: '초대코드 복사' })).toBeEnabled()

    fireEvent.click(screen.getByRole('tab', { name: '내 사진' }))
    await waitFor(() => expect(client.listPhotos).toHaveBeenLastCalledWith('album-real', expect.objectContaining({ member_ids: ['member-real'] })))
  })

  it('shows analyzed tags and filters unresolved faces', async () => {
    const client = {
      getAlbum: vi.fn().mockResolvedValue({ id: 'album-real', name: '키로톤', invite_code: 'DEMO26', created_at: '2026-09-20T00:00:00Z', photo_count: 0, members: [], tags: ['실내', '노트북'] }),
      listPhotos: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 8, total: 0, total_pages: 1 }),
      getStatus: vi.fn().mockResolvedValue({ pending: 0, processing: 0, done: 0, failed: 0 }),
    } as unknown as ApiClient

    render(<Gallery client={client} albumId="album-real" currentMemberId="member-real" onOpen={() => {}} onCoverage={() => {}} />)
    await screen.findByRole('button', { name: '노트북' })

    fireEvent.click(screen.getByRole('button', { name: '노트북' }))
    await waitFor(() => expect(client.listPhotos).toHaveBeenLastCalledWith('album-real', expect.objectContaining({ tag: '노트북' })))
    fireEvent.click(screen.getByRole('button', { name: '미등록 인물' }))
    await waitFor(() => expect(client.listPhotos).toHaveBeenLastCalledWith('album-real', expect.objectContaining({ tag: '노트북', face_status: 'unregistered' })))
  })

  it('loads detail members from the runtime album instead of a sample ID', async () => {
    const getAlbum = vi.fn().mockResolvedValue({
      id: 'album-real', name: '부산', invite_code: 'BUSAN1', created_at: '2026-09-20T00:00:00Z', photo_count: 1,
      members: [{ id: 'member-real', display_name: '민지', reference_key: null, reference_indexed: false }],
    })
    const getPhoto = vi.fn().mockResolvedValue({
      id: 'p-1', album_id: 'album-real', filename: 'real.jpg', image_url: '/real.jpg', thumb_url: '/real.jpg',
      captured_at: null, created_at: '2026-09-20T00:00:00Z', analysis_status: 'done', analysis_error: null,
      provider: 'fixture', mode: 'mock', face_count: 1, shot_type: 'solo', tags: [], quality: {},
      uncertain_face_count: 1, unregistered_face_count: 1,
      best_score: null, is_best: false,
      members: [{ member_id: 'member-real', display_name: '민지', similarity: 99, source: 'auto', excluded: false }],
    })
    const client = { getAlbum, getPhoto } as unknown as ApiClient

    render(<PhotoDetail client={client} albumId="album-real" photoId="p-1" onBack={() => {}} />)

    await screen.findByAltText('real.jpg')
    expect(getPhoto).toHaveBeenCalledWith('p-1')
    expect(getAlbum).toHaveBeenCalledWith('album-real')
    expect(getAlbum).not.toHaveBeenCalledWith('album-demo')
    expect(screen.getByText(/샘플 분석 · 실제 얼굴 인식/)).toBeTruthy()
    expect(screen.getByText(/확인 필요 1명/)).toBeTruthy()
    expect(screen.getByText('미등록 인물 1명')).toBeTruthy()
  })
})
