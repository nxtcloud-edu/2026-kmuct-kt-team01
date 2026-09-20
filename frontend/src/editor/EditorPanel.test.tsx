// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EditorPanel from './EditorPanel'

const photoId = '90bb8450-6a7e-4a6b-a00c-1a8d6f70d136'
const memberId = 'b8ea92b4-958b-4779-94b7-3d2fd116b047'
const firstId = '27ccdbef-a78f-4c7b-b66a-4b0121bb3e92'
const members = [{ id: memberId, display_name: '지민' }]
const first = { id: firstId, photo_id: photoId, author_member_id: memberId, parent_id: null, number: 1,
  created_at: '2026-09-20T00:00:00Z', brightness: 1.2, saturation: 0.8,
  approval_count: 0, required_count: 1, required_member_ids: [memberId], approved_member_ids: [],
  is_final: false, can_approve: true, approved_by_me: false, approval_blocked_reason: null,
  provider: 'fixture', mode: 'fixture', storage_mode: 'fixture' }
const fetchMock = vi.fn<typeof fetch>()
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => vi.stubGlobal('fetch', fetchMock))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); fetchMock.mockReset() })

describe('EditorPanel', () => {
  it('shows empty versions and restores settings after reset', async () => {
    fetchMock.mockResolvedValue(json({ versions: [] }))
    render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={() => {}} />)
    await screen.findByText('아직 저장된 보정 버전이 없어요.')
    fireEvent.change(screen.getByLabelText('밝기'), { target: { value: '1.4' } })
    fireEvent.click(screen.getByRole('button', { name: '초기화' }))
    expect((screen.getByLabelText('밝기') as HTMLInputElement).value).toBe('1')
    expect(fetchMock.mock.calls[0]![0]).toBe(`/api/photos/${photoId}/edits`)
  })

  it('restores selected version and saves a child with full settings', async () => {
    const saved = { ...first, id: 'b1d22fa9-df94-447b-8362-32ee6e4ad181', parent_id: firstId, number: 2, brightness: 1.3 }
    fetchMock.mockResolvedValueOnce(json({ versions: [first] })).mockResolvedValueOnce(json(saved, 201))
    const onSaved = vi.fn()
    render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={onSaved} />)
    fireEvent.click(await screen.findByRole('button', { name: /버전 1 선택/ }))
    expect((screen.getByLabelText('채도') as HTMLInputElement).value).toBe('0.8')
    fireEvent.change(screen.getByLabelText('밝기'), { target: { value: '1.3' } })
    fireEvent.click(screen.getByRole('button', { name: '새 버전 저장' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    const options = fetchMock.mock.calls[1]![1]!
    expect(JSON.parse(options.body as string)).toEqual({ brightness: 1.3, saturation: 0.8, parent_id: firstId })
    expect(options.credentials).toBe('same-origin')
    expect(await screen.findByRole('button', { name: /버전 2 선택/ })).toBeTruthy()
    expect(screen.getAllByText('테스트 저장소')).toHaveLength(2)
  })

  it('only compares while pointer or keyboard is held', async () => {
    fetchMock.mockResolvedValue(json({ versions: [] }))
    render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={() => {}} />)
    await screen.findByText('아직 저장된 보정 버전이 없어요.')
    const compare = screen.getByRole('button', { name: '누르는 동안 원본 보기' })
    fireEvent.pointerDown(compare)
    expect(screen.getByAltText('보정 미리보기').style.filter).toBe('none')
    fireEvent.pointerCancel(compare)
    expect(screen.getByAltText('보정 미리보기').style.filter).toContain('brightness')
    fireEvent.keyDown(compare, { key: ' ' })
    expect(screen.getByAltText('보정 미리보기').style.filter).toBe('none')
    fireEvent.blur(compare)
    expect(screen.getByAltText('보정 미리보기').style.filter).toContain('saturate')
  })

  it('shows save error without fake success and allows retry', async () => {
    fetchMock.mockResolvedValueOnce(json({ versions: [] })).mockResolvedValueOnce(json({ code: 'EDIT_SAVE_FAILED', message: '저장 실패' }, 503))
    const onSaved = vi.fn()
    render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={onSaved} />)
    await screen.findByText('아직 저장된 보정 버전이 없어요.')
    fireEvent.click(screen.getByRole('button', { name: '새 버전 저장' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '저장 실패')
    expect(onSaved).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: '새 버전 저장' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('refreshes all final flags after approval and allows cancellation', async () => {
    const approved = { ...first, approved_by_me: true, is_final: true, approval_count: 1 }
    fetchMock.mockResolvedValueOnce(json({ versions: [first] })).mockResolvedValueOnce(json(approved)).mockResolvedValueOnce(json({ versions: [approved] }))
    render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: '버전 1 승인' }))
    expect(await screen.findByRole('button', { name: '버전 1 승인 취소' })).toBeTruthy()
    expect(screen.getByText('최종본')).toBeTruthy()
    expect(fetchMock.mock.calls[1]![0]).toBe(`/api/edits/${firstId}/approve`)
  })

  it('does not call the real API for sample photo IDs', async () => {
    render(<EditorPanel photoId="p-1" originalUrl="/sample.jpg" members={members} onSaved={() => {}} />)
    expect(await screen.findByText(/샘플 사진에서는/)).toBeTruthy()
    expect(fetchMock).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: '새 버전 저장' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('clears state and aborts old requests when photo changes', async () => {
    fetchMock.mockResolvedValueOnce(json({ versions: [first] })).mockResolvedValueOnce(json({ versions: [] }))
    const view = render(<EditorPanel photoId={photoId} originalUrl="/one.jpg" members={members} onSaved={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /버전 1 선택/ }))
    const oldSignal = fetchMock.mock.calls[0]![1]!.signal!
    view.rerender(<EditorPanel photoId="5886a303-4d27-43f6-8985-3ddf36aa533e" originalUrl="/two.jpg" members={members} onSaved={() => {}} />)
    await screen.findByText('아직 저장된 보정 버전이 없어요.')
    expect(oldSignal.aborted).toBe(true)
    expect((screen.getByLabelText('밝기') as HTMLInputElement).value).toBe('1')
    expect(screen.queryByRole('button', { name: /버전 1 선택/ })).toBeNull()
  })

  it('prevents duplicate saves and ignores late success after unmount', async () => {
    let finish: (value: Response) => void = () => {}
    fetchMock.mockResolvedValueOnce(json({ versions: [] })).mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const onSaved = vi.fn()
    const view = render(<EditorPanel photoId={photoId} originalUrl="/photo.jpg" members={members} onSaved={onSaved} />)
    await screen.findByText('아직 저장된 보정 버전이 없어요.')
    const save = screen.getByRole('button', { name: '새 버전 저장' })
    fireEvent.click(save)
    fireEvent.click(save)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    view.unmount()
    finish(json(first, 201))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(onSaved).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls[1]![1]!.signal!.aborted).toBe(true)
  })

  it('refreshes final status when album members change on the same photo', async () => {
    fetchMock.mockResolvedValueOnce(json({ versions: [{ ...first, is_final: true }] })).mockResolvedValueOnce(json({ versions: [first] }))
    const view = render(<EditorPanel photoId={photoId} originalUrl="/one.jpg" members={members} onSaved={() => {}} />)
    await screen.findByText('최종본')
    view.rerender(<EditorPanel photoId={photoId} originalUrl="/one.jpg" members={[...members, { id: 'another-member', display_name: '새 멤버' }]} onSaved={() => {}} />)
    await waitFor(() => expect(screen.queryByText('최종본')).toBeNull())
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('refreshes other members approvals when the window regains focus', async () => {
    fetchMock.mockResolvedValueOnce(json({ versions: [first] })).mockResolvedValueOnce(json({ versions: [{ ...first, is_final: true }] }))
    render(<EditorPanel photoId={photoId} originalUrl="/one.jpg" members={members} onSaved={() => {}} />)
    await screen.findByRole('button', { name: '버전 1 승인' })
    fireEvent(window, new Event('focus'))
    expect(await screen.findByText('최종본')).toBeTruthy()
  })
})
