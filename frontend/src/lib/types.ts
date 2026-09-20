export type AnalysisStatus = 'pending' | 'processing' | 'done' | 'failed'
export type ShotType = 'unknown' | 'no_face' | 'solo' | 'group'
export type DataMode = 'mock' | 'api'

export interface ActiveAlbum {
  albumId: string
  memberId: string
  displayName: string
}

export interface Member {
  id: string
  display_name: string
  reference_key: string | null
  reference_indexed: boolean
}

export interface Album {
  id: string
  name: string
  invite_code: string
  created_at: string
  photo_count: number
  members: Member[]
}

export interface PhotoMember {
  member_id: string
  display_name: string
  similarity: number | null
  source: 'auto' | 'manual'
  excluded: boolean
}

export interface MemberChange {
  member_id: string
  excluded: boolean
}

export interface PhotoQuality {
  sharpness?: number
  brightness?: number
  eyes_open_ratio?: number
}

export interface Photo {
  id: string
  album_id: string
  filename: string
  image_url: string
  thumb_url: string
  captured_at: string | null
  created_at: string
  analysis_status: AnalysisStatus
  analysis_error: string | null
  provider: string | null
  mode: string | null
  face_count: number
  uncertain_face_count?: number
  unregistered_face_count?: number
  shot_type: ShotType
  tags: string[]
  quality: PhotoQuality
  best_score: number | null
  is_best: boolean
  members: PhotoMember[]
}

export interface PhotoFilters {
  member_ids?: string[]
  shot_type?: ShotType
  tag?: string
  only_best?: boolean
  sort?: 'captured_desc' | 'best_desc'
  page?: number
}

export interface PageResult<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface UploadResult {
  filename: string
  ok: boolean
  photo: Photo | null
  error: ApiErrorBody | null
}

export interface UploadBatchResponse {
  results: UploadResult[]
}

export interface AnalysisCounts {
  pending: number
  processing: number
  done: number
  failed: number
}

export interface CoverageRow {
  member_id: string
  display_name: string
  photo_count: number
}

export interface Coverage {
  total: number
  members: CoverageRow[]
}

export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
}

export class ApiError extends Error {
  code: string
  status: number
  details?: unknown

  constructor(body: ApiErrorBody, status = 500) {
    super(body.message)
    this.name = 'ApiError'
    this.code = body.code
    this.status = status
    this.details = body.details
  }
}
