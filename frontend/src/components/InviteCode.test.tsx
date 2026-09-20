import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { InviteCode } from './InviteCode'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('shows the exact code and copies it through the clipboard in a secure context', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  render(<InviteCode code="aB9_xY-2" />)
  expect(screen.getByLabelText('앨범 초대 코드')).toHaveValue('aB9_xY-2')
  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(writeText).toHaveBeenCalledWith('aB9_xY-2')
})

it('falls back to selected text copying when secure clipboard access is denied', async () => {
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
  const execCommand = vi.fn().mockReturnValue(true)
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
  render(<InviteCode code="aB9_xY-2" />)
  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(execCommand).toHaveBeenCalledWith('copy')
})

it('uses the synchronous selection fallback directly on an HTTP page', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  const execCommand = vi.fn().mockReturnValue(true)
  vi.stubGlobal('isSecureContext', false)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
  render(<InviteCode code="aB9_xY-2" />)

  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(writeText).not.toHaveBeenCalled()
  expect(execCommand).toHaveBeenCalledWith('copy')
  expect(screen.getByLabelText('앨범 초대 코드')).toHaveFocus()
})

it('keeps the code selected for manual copying when automatic copying fails', async () => {
  vi.stubGlobal('isSecureContext', false)
  vi.stubGlobal('navigator', {})
  Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn().mockReturnValue(false) })
  render(<InviteCode code="aB9_xY-2" />)
  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('직접 복사'))
  expect(screen.getByLabelText('앨범 초대 코드')).toHaveValue('aB9_xY-2')
  expect(screen.getByLabelText('앨범 초대 코드')).toHaveFocus()
})
