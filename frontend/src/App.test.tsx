// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
})
