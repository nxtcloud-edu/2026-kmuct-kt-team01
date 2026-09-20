// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import App, { loadActiveAlbum } from './App'

const activeAlbum = { albumId: 'album-real', memberId: 'member-real', displayName: '민지' }

beforeEach(() => window.sessionStorage.clear())
afterEach(() => { cleanup(); window.sessionStorage.clear() })

describe('App refresh recovery', () => {
  it('restores the active album after a browser refresh', async () => {
    window.sessionStorage.setItem('zzik.activeAlbum.mock', JSON.stringify(activeAlbum))

    render(<App />)

    await screen.findByText('우리들의 제주')
    expect(screen.getByText('민지')).toBeTruthy()
    expect(screen.queryByText('초대받은 앨범이 있나요?')).toBeNull()
  })

  it('ignores malformed saved navigation state', async () => {
    window.sessionStorage.setItem('zzik.activeAlbum.mock', '{bad json')

    expect(loadActiveAlbum()).toBeNull()
    render(<App />)

    await waitFor(() => expect(screen.getByText('초대받은 앨범이 있나요?')).toBeTruthy())
  })

  it('leaves the current album and allows another invite-code flow', async () => {
    window.sessionStorage.setItem('zzik.activeAlbum.mock', JSON.stringify(activeAlbum))
    render(<App />)
    await screen.findByText('우리들의 제주')

    fireEvent.click(screen.getByRole('button', { name: '현재 앨범 나가기' }))

    await screen.findByText('초대받은 앨범이 있나요?')
    expect(window.sessionStorage.getItem('zzik.activeAlbum.mock')).toBeNull()
    expect(screen.queryByText('민지')).toBeNull()

    fireEvent.change(screen.getByLabelText('초대 코드'), { target: { value: 'NEXT_album-2' } })
    fireEvent.change(screen.getByLabelText('내 이름'), { target: { value: '수진' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'pass1234' } })
    fireEvent.click(screen.getByRole('button', { name: /앨범 들어가기/ }))

    await screen.findByText('내 사진을 찾아드릴게요')
    await waitFor(() => expect(JSON.parse(window.sessionStorage.getItem('zzik.activeAlbum.mock') ?? '{}')).toMatchObject({ displayName: '수진' }))
  })
})
