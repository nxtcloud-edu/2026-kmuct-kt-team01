# ROLE-05 작업 상태

현재 단계: **운영 연결과 조립 수락 검사 완료, main 병합 완료**.

## 최종 통합 완료 — 2026-09-20

- 통합 PR #14, 후속 수락 수정 PR #18이 `main`에 병합됐다.
- 업로드한 PNG/JPEG 원본 바이트와 해시를 보존하고 썸네일만 별도 생성한다.
- SQLAlchemy repository, create-only 저장소 adapter, 서명 세션, 보정 API, 서버 미리보기와 다운로드가 연결됐다.
- no_face 또는 확정 멤버 0명은 업로더 1명이 승인하며, 최신 승인본 취소 시 이전 충족본으로 돌아간다.
- 분석 중 수동 인물 제외가 발생해도 worker가 최신 관계를 잠금·재조회해 사용자 결정을 보존한다.
- `docs/assembly/checks/role5_acceptance.py` 4개를 포함한 Python **222 tests**, 프론트 **23 tests**와 build가 통과했다.
- 실제 AWS·전용 PostgreSQL 부하·EC2 배포 검증은 인프라 작업으로 남아 있으며 AWS 권한은 #10에서 추적한다.

아래 내용은 역할 브랜치에서 통합 전 작성한 작업 이력이다.

## 최신 인계 — 2026-09-20

- 직전 공개 head: `a9444e15390a2d42d5c41c1c5deab31bc278bd0c`. 이번 후속 커밋의 full SHA는 #3 READY 댓글로 전달한다.
- 3번 [ACK/정책 결정](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/3#issuecomment-5746567388)을 반영했다.
  분석 완료 후 no_face 또는 유효한 확정 멤버가 0명이면 업로더 1명 승인. uncertain은 대상으로 추가하지 않으며 전역 차단 조건도 아니다.
  분석 미완료/업로더 탈퇴는 차단하고, 새 버전 자동 승인은 없다. 최종본 최대 number 및 취소 시 과거 충족본 fallback 유지.
- 새 정책 네 회귀 사례가 기존 코드에서 실패함을 확인 후 수정. no_face와 확정 멤버가 함께 있는 경우도 추가 검사.
- Python 3.13 역할 전용 의존성: `pytest backend/tests/role5 -q -W error` **51 passed**.
- `assemble/20260920` **3e6fa6b346c9912ed9e9cb4ec717dbfe93b9f334**를 임시 snapshot으로 추출하고 최신 edits.py/role5 테스트를 추가했다.
  후보의 실제 requirements(Pillow 11.3.0, FastAPI 0.117.1)로 별도 가상환경에서 **163 passed**.
  Starlette/AnyIO의 BlockingPortal DeprecationWarning 1건. 라이브러리 상향 없이도 역할 코드 호환 확인.
  이것은 코드·테스트 합성 검사이며 미구현 운영 edit adapter까지 연결된 E2E 검사는 아니다.
- ROLE-02 **92a7fb37fd0b385658ed92a70fbd1da5bc3be6f5** snapshot 기본 `npm test` **20 passed**, `npm run build` 통과.
  PhotoDetail에 EditorPanel props 연결을 확인했다. 추가 회귀 검사에서 `getAlbum(photo.album_id)` 대신
  `getAlbum('album-demo')` 호출을 재현했다(별도 임시 테스트 1 failed). #7로 실제 앨범 ID 연결 수정을 요청한다.
  이 테스트는 역할 2 소유 파일에 커밋하지 않았다. 전체 live 상세 흐름은 미완료다.
- 3번의 운영 어댑터와 원본 보존 #4, 미리보기/보정본 다운로드 계약은 남아 있다.
  PostgreSQL 동시성·실제 S3·AWS·전체 브라우저 E2E는 미검증이다.
- 후보 병합 시 .gitignore add/add 충돌은 assemble 쪽이 역할 5의 여섯 패턴을 모두 포함한다는 ROLE-02 정보를 전달받았다.
  최종 통합 및 병합은 ROLE-03가 수행한다.

## Git·외부 상태

- 저장소: https://github.com/nxtcloud-edu/2026-kmuct-kt-team01
- 제출 BASE=main, RUN=20260920. 역할 1의 docs/TEAM_SETUP.md에서 확인.
- 로컬 Git 로그인: tkdgur3207. 저장소 push/admin 권한을 GitHub API에서 확인했다.
- GitHub CLI 미설치. 앱 커넥터 계정은 eigenz1로 달라 쓰기에 사용하지 않았다.
- 시작/현재 HEAD: `d0be0d8ac634b677bb25c3bb3aa2944f6697bd4a` (Update README).
- 사용자에게 로컬 구현과 검사 결과를 제시했고 **2026-09-20 커밋·push 승인을 받았다**.
- 현재 변경은 승인된 첫 기능 커밋 대상이다. 원격 PR/커밋 링크는 게시 후 아래 발행 기록에 추가한다.
- 역할 브랜치 `work/20260920/role-5`를 origin/main에서 생성했다. 현재는 로컬 미커밋 변경이다.
- 시작 시 이미 삭제 상태였던 README.md, untracked 00-START-HERE.md/ROLE_01~05.md는 수정하지 않았다.
- AWS 호출·배포·병합은 수행하지 않았다. 협업 이슈 #3/#4/#7과 2번 PR COMMENT 리뷰를 본인 계정으로 게시했다.
- 가져온 현재 팀 기반: role-1 `bf8da01745de143d8884b477237439dce5c2025a`,
  role-2 `5213e685dd6d66f01cc0e707f657f4d0d3fc3e8e`, role-3 `aac5017902061c667266a37223457eb1b2bb4bb2`.
  다른 담당자 코드를 작업 트리에 덮어쓰거나 병합하지 않았다. 프론트는 임시 snapshot에만 추출해 검사했다.

## 기능 상태

| 항목 | 상태 | 근거·한계 |
|---|---|---|
| 원본 기반 밝기·채도 렌더 | 완료(로컬) | 실제 Pillow, 원본 SHA 불변·결과 JPEG 검사 |
| JPEG/PNG 검사·25 MiB·20MP 제한·EXIF 방향 | 완료(로컬) | 형식/손상/상한/회전 테스트 |
| ICC→sRGB·투명 배경 | 완료(로컬) | RGBA/LA/sRGB 검사, 실제 CMYK ICC 수동 검사 |
| 새 버전·parent·번호·분리 파일 | 완료(계약 fixture) | 원본 재렌더 동일성·동시 저장·실패 rollback |
| 네 개 보정/승인 API | 완료(주입형 router) | ASGI 경유 요청/오류/권한 검사 |
| 중복 승인 방지·취소·최종본 하나 | 완료(계약 fixture) | 명시 승인 집계·최대 number·과거 후보 fallback |
| 인물/멤버 변경 무효화 | 부분 | hook+원자적 fixture 전이 검사 완료, 3번 handler 연결 필요 |
| 불확실 인물·no_face 업로더 승인 | 부분 | 3번 확정 정책 반영/검사 완료, 운영 DTO 매핑 필요 |
| 파일·설정·승인·최종 상태 재시작 후 보존 | 완료(계약 fixture) | SQLite `_test.sqlite3`와 임시 파일 재개방 |
| 실제 PostgreSQL·S3·서명 세션 연결 | 부분 | 3번 기반/모델 확인, 보정 전용 어댑터 연결 요청 #3 |
| 원본/보정본 실제 다운로드 | 미검증 | 로컬 저장 파일 바이트 검증만 완료, 다운로드 API 통합 필요 |
| EditorPanel·모바일 UI | 부분(통합) | mount 확인, 컴포넌트 fixture 통과. 상세 album-demo 고정 요청 수정 필요 #7 |
| CSS/서버 미리보기 일치 | 부분 | 합성 RGB 비교에서 차이 확인, 서버 미리보기 계약 결정 필요 |
| 2번 PR 교차 검토·2번 피드백 반영 | 부분 | #2의 지정 head/API diff에 COMMENT 리뷰 완료, 후속 피드백 대기 |
| 최종 후보 E2E·EC2 재시작·2GB 실측 | 미검증 | 배포/후보 없음 |
| 댓글·수정 요청 | 미착수 | T3, 공유 스키마 의존·핵심 통합 우선 |

## 파일

- `backend/app/edits.py`: 렌더·DTO/Protocol·서비스·router. 운영 모델/앱은 생성하지 않음.
- `backend/tests/role5/`: 합성 사진·SQLite/local storage 계약 fixture와 48개 테스트.
- `frontend/src/editor/`: EditorPanel.tsx/CSS, 10개 React 테스트, 독립 테스트 config. React 프로젝트/패키지 중복 생성 없음.
- `backend/tests/role5/dependencies.txt`: 검증한 의존성 버전 고정. 공통 requirements.txt 대체물이 아님.
- `docs/assembly/role-5-integration.md`: 2/3번 연결 방법·정책 확인·요청 초안·미리보기 차이.
- `docs/assembly/role-5-plan.md`: 실행 계획과 진행 기록.
- `.gitignore`: 이 작업의 로컬 Python 환경·도구·캐시 제외.

## 실행한 검사와 결과

실제 네트워크/운영 DB를 사용하지 않았다. 데이터는 자동 생성한 합성 이미지와 pytest 임시 디렉터리뿐이다.

```powershell
.venv-role5-py313/Scripts/python.exe -m pytest -q -W error
# Python 3.13.15: 48 passed in 2.19s

.venv-role5/Scripts/python.exe -m pytest -q -W error
# Python 3.14.7: 48 passed in 2.23s

.venv-role5-py313/Scripts/python.exe -m compileall -q backend
# 성공

.venv-role5/Scripts/uv.exe pip check --python .venv-role5-py313/Scripts/python.exe
# 21 packages, All installed packages are compatible
```

- Windows RSWOP.icm 실제 CMYK 프로필로 JPEG 생성→렌더→픽셀 `(223,170,128)` 검사 성공.
  시스템 프로필을 저장소에 복사/배포하지 않았다. 이 수동 검사는 Windows 환경에서만 수행했다.
- 렌더/서비스/router 작성 전 미구현 import 실패를 확인하고 단계별 구현 후 통과시켰다.
- 독립 코드 검토에서 세션 HTTPException이 503으로 바뀌는 문제, CMYK ICC 변환 순서 문제를 발견했다.
  두 회귀 테스트가 각각 실패하는 것을 확인하고 수정 후 전체 검사 통과.
- 엄격 경고 검사에서 fixture SQLite 연결 누수가 발견됐다. context manager의 commit과 close가 다른 동작임을 확인해
  명시 close를 추가했고 Python 3.13/3.14 전체 검사가 모두 통과했다.
- UTF-8·줄 끝 공백·Python 컴파일 검사 성공. 기존 tracked diff에 `git diff --check` 성공.
- 3번 앱에 이미 등록된 ApiError 핸들러를 보존하는 회귀 테스트 추가: 실패 확인 후 수정, 48개 전체 통과.
- 2번 실제 lockfile의 임시 frontend snapshot에서 `vitest run --config src/editor/vitest.config.ts`: 10 passed.
- 같은 snapshot에서 `npm run build`: TypeScript+Vite 성공. 공통 앱에 컴포넌트 mount는 아직 아니다.
- 해당 role-2 head의 기본 `npm test`는 없는 `src/test/setup.ts` 때문에 실패한다. 타인 파일을 수정하지 않고 전용 config로 검사했다.
- 실제 Chrome 390px/1280px 합성 fixture: 저장→승인→취소, 가로 넘침 없음, 런타임 오류 없음. 모바일 screenshot을 직접 확인했다.
- 프론트 독립 검토에서 같은 사진의 승인 상태가 갱신되지 않는 문제를 확인했다. 멤버 ID 변경·focus·visible 10초마다 재조회,
  in-flight/revision 보호, 수동 새로고침을 추가하고 두 회귀 테스트가 실패→통과하는 것을 확인했다.
- 실사진 정확도, 실제 AWS, 브라우저 육안 일치, 2000장 성능은 측정하지 않았다.

재현 환경은 별도 Python 3.13 가상환경에 `backend/tests/role5/dependencies.txt`를 설치하고 저장소 루트에서 pytest를 실행한다.
테스트 fixture를 운영 app으로 mount하지 않는다.

## 남은 의존성과 결정

1. 1번: 최종 환경의 프로세스 수·메모리 예산 확인. BASE/RUN은 확인 완료.
2. 3번: 운영 repository/storage/세션 주입, 공통 의존성 반영, 인물 변경 hook 연결.
3. 3·4번: 확정/제외 인물을 PhotoSnapshot에 정확히 매핑. 승인 대상/최종본 정책은 #3 결정 반영 완료.
4. 2·3번: CSS 근사와 서버 권위 렌더 차이 처리, 인증된 미리보기·보정본 다운로드 API 결정.
5. 2번: mount 완료. 실제 앨범 ID 전달 수정 후 실제 API 모바일 교차 검토.
6. 커밋/push 사용자 승인 완료. 팀 통합과 후속 검토를 진행한다.

## 협업 요청 상태

- [#3 backend-adapters](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/3): ACK 수신, 정책 반영 소스 READY. 운영 어댑터/원자적 무효화 연결은 미완료.
- [#4 preserve-upload-original](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/4): REQUESTED. 업로드 raw 대신 재인코딩 객체가 저장되는 원본 손실 문제.
- [#7 editor-integration](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/7): 프론트 mount 응답 수신/소스 확인. 실제 앨범 ID 결함 및 서버 미리보기/다운로드 미완료로 열어 둠.
- #3/#7에 실제 role-5 PR/full SHA/검사 결과를 추가로 전달했다. 상대 작업 완료를 의미하지 않는다.
- [2번 PR 리뷰](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/pull/2#pullrequestreview-5258615747): COMMENTED, 승인 아님.
  head `5213e685dd6d66f01cc0e707f657f4d0d3fc3e8e`의 API 클라이언트 diff만 검토.
  인물 수정 payload·정렬 파라미터·파일별 업로드 결과·누락된 공통 테스트 setup을 지적했다.
  2번이 `1df5ad3f6f65e9e45025eb495b06f44b544a42a2`에서 지적 사항을 반영했다고 답하고 재검토를 요청했다.
  [수정 답변](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/pull/2#issuecomment-5746518455).
  최신 `dc0bb62412feb00a4cc7ad5fe0be12fd66adbf57`에서 네 수정의 실제 diff를 확인하고 전체 프론트 테스트 20개/build를 검사했다.
  **이전 네 지적 사항은 요청자 확인 완료(APPLIED)**. 전체 PR·실제 API E2E 승인은 아니다.
  [재검토 결과](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/pull/2#pullrequestreview-5258698258)를 COMMENT로 전달했다.
  위 리뷰 이후 #3/#7에 응답이 도착해 최신 인계에 반영했다. #4 응답은 아직 없다.

## 다음 재개 순서

이번 ROLE-05 변경의 커밋/push는 승인됐다. 같은 작업에 대해 재승인을 요구하지 않는다.
원격 ref·열린 PR을 다시 확인하고 이미 존재하는 역할 브랜치/PR을 재사용한다.
승인된 경우 이 작업 파일만 stage하고 사용자 README 삭제/역할 문서를 제외한다.
3번/2번 응답이 오면 갱신된 실제 인터페이스를 읽고 인계 문서의 제안을 합의한 계약에 맞춰 연결한다.
최종 후보 다운로드와 재시작 테스트가 통과하기 전에는 전체 완료로 보고하지 않는다.
