import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { InviteCodeCopyButton } from './InviteCode'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('copies the exact invite code through the clipboard in a secure context', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  render(<InviteCodeCopyButton code="aB9_xY-2" />)

  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(writeText).toHaveBeenCalledWith('aB9_xY-2')
})

it('falls back to hidden selected text when secure clipboard access is denied', async () => {
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
  const execCommand = vi.fn().mockReturnValue(true)
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
  render(<InviteCodeCopyButton code="aB9_xY-2" />)

  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(execCommand).toHaveBeenCalledWith('copy')
  expect(document.querySelector('textarea')).toBeNull()
})

it('uses the synchronous fallback directly on an HTTP page without showing another code box', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  const execCommand = vi.fn().mockReturnValue(true)
  vi.stubGlobal('isSecureContext', false)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
  render(<InviteCodeCopyButton code="aB9_xY-2" />)

  fireEvent.click(screen.getByRole('button', { name: '초대코드 복사' }))

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('복사했어요'))
  expect(writeText).not.toHaveBeenCalled()
  expect(execCommand).toHaveBeenCalledWith('copy')
  expect(screen.queryByLabelText('앨범 초대 코드')).toBeNull()
  expect(document.querySelector('textarea')).toBeNull()
})
