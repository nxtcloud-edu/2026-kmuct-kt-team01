# Role 2 — frontend handoff

- 실행 ID: `20260920`
- 공식 저장소: `nxtcloud-edu/2026-kmuct-kt-team01`
- 브랜치: `work/20260920/role-2`
- 기준 브랜치: `main`
- 담당 계정: `seopseopi`
- Draft PR: https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/pull/2
- 최근 기능 커밋: `1df5ad3f6f65e9e45025eb495b06f44b544a42a2`
- 현재 단계: 프론트 mock 구현 및 브라우저 검증 완료, 실제 백엔드와 역할 5 컴포넌트 연결 대기

## 기능별 커밋

1. `7f17659` — React 19, TypeScript, Vite 기반과 앱 셸
2. `203a94e` — 도메인 타입, `/api` 클라이언트, 명시적 sample/mock 클라이언트
3. `5213e68` — 앨범 생성·참여와 기준 얼굴 등록
4. `795b73f` — 갤러리, 2초 상태 폴링, 멤버 AND 필터, 태그, 페이지네이션, ZIP 선택
5. `6cc2524` — 사진 상세, 인물 수정, 품질, 원본 요청, 누락 현황, 역할 5 편집 슬롯
6. `b5b611c` — API·상태 컴포넌트 테스트와 실행 문서
7. `1df5ad3` — 역할 5 리뷰 반영, 실제 백엔드 payload·정렬·업로드 결과 정합화

## 구현 상태

- 완료: 앨범 생성/초대코드 참여 화면
- 완료: 기준 얼굴 등록과 `NO_FACE`/`MULTIPLE_FACES` 개별 안내
- 완료: 전체/내 사진/단체샷/베스트컷, 멤버 AND 필터, 태그, 페이지네이션
- 완료: 2초 분석 현황 폴링, 사진 선택과 ZIP 다운로드 요청
- 완료: 사진 상세, 인물 수동 변경, 품질/분석 상태, 원본 다운로드 요청
- 완료: 멤버별 사진 누락 현황
- 완료: `/api` 상대경로, `credentials: include`, 공통 JSON 오류 변환
- 완료: 샘플과 실제 API 모드 분리, 샘플 화면 배지
- 부분: 업로드 API와 진행 UI. 파일별 성공/실패 표시는 실제 백엔드 응답 연결 후 보완
- 미착수: 역할 5 소유의 보정 버전·비교·승인 내부 구현. `EditorPanelProps`와 슬롯만 제공
- 미검증: 실제 FastAPI 세션/업로드/다운로드, EC2 배포 주소의 모바일 브라우저

## 공개 연결 지점

- API 타입 및 구현: `frontend/src/lib/api.ts`
- 도메인 타입: `frontend/src/lib/types.ts`
- 역할 5 편집 props: `frontend/src/components/EditorSlot.tsx`
- 실제 API 모드: URL query `?data=api`

## 검사

- `npm run typecheck` — 통과
- `npm test` — 2 files, 10 tests 통과
- `npm run build` — 통과
- `npm audit --audit-level=moderate` — 취약점 0건
- Playwright — 데스크톱/390px 모바일, 랜딩→앨범→사진 상세, 콘솔 오류 0건

## 남은 의존성

- 역할 3: 실제 FastAPI 응답과 `HttpApiClient` 연결, 다중 업로드 파일별 결과 확인
- 역할 5: `EditorPanelProps` 기반 보정·버전·승인 컴포넌트 제공
- 역할 1: Nginx 정적 빌드와 `/api` proxy 환경에서 검증

## 요청 상태

- `ZZIK:20260920:role-2:api-integration-01` → role-3, REQUESTED
  - https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/6
- `ZZIK:20260920:role-2:editor-slot-01` → role-5, REQUESTED
  - https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/5
- PR #2 교차 검토자 `tkdgur3207` 지정 완료
- role-5 계약 리뷰 `5258615747` → APPLIED (`1df5ad3`), 최신 head 재검토 요청
- `ZZIK:20260920:role-2:dependency-session-01` → role-1, REQUESTED
  - role-3/5 요청 무응답에 따른 세션·전달 상태 확인: https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/11
