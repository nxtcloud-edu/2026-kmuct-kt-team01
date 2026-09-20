import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../lib/types'
import { EmptyState, ErrorState } from './AsyncState'

describe('공통 비동기 상태', () => {
  it('권한 오류를 통신 오류와 다른 문구로 안내한다', () => {
    render(<ErrorState error={new ApiError({ code: 'FORBIDDEN', message: '참여한 멤버만 볼 수 있어요.' }, 403)} />)
    expect(screen.getByRole('heading', { name: '이 앨범을 볼 권한이 없어요' })).toBeInTheDocument()
    expect(screen.getByText('참여한 멤버만 볼 수 있어요.')).toBeInTheDocument()
  })

  it('빈 결과의 원인과 다음 행동을 표시한다', () => {
    render(<EmptyState title="조건에 맞는 사진이 없어요" description="필터를 바꿔보세요." />)
    expect(screen.getByText('필터를 바꿔보세요.')).toBeInTheDocument()
  })
})
