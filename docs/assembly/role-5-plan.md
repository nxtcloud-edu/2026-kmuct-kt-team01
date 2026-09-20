# ROLE-05 구현 계획

기준: 사용자가 실행하도록 지정한 `ROLE_05.md` 확정 계약.
목표: 원본 보존 렌더링과 버전·명시적 승인 API를 구현하고, 공통 서버 없이 계약 fixture로 검증한다.

## 제약과 현재 상태

- 저장소: nxtcloud-edu/2026-kmuct-kt-team01. 원격 HEAD: main, d0be0d8ac634b677bb25c3bb3aa2944f6697bd4a.
- 로컬 인증: tkdgur3207, 저장소 push 권한 확인. 앱 커넥터 계정은 다르므로 쓰기에 사용하지 않는다.
- 시작 시 BASE/RUN 미확정 → 작업 중 1번 설정에서 main/20260920 확인. **커밋·push는 결과 검토 후 별도 허락을 받는다**.
- 작업 전 README.md가 삭제돼 있었고 역할 문서가 untracked였다. 이를 건드리거나 커밋에 포함하지 않는다.
- 공통 모델·migration·requirements.txt·frontend 프로젝트·배포 파일은 각 담당 소유다.
- 실제 DB/S3/세션 어댑터는 3번 의존성. 테스트용 SQLite `_test.sqlite3`와 임시 파일만 사용한다.
- Python 3.13 목표. 설치된 Python 3.14에서도 검사하고 가능한 경우 3.13을 별도 확보한다.

## 설계

`backend/app/edits.py`에 Pillow 렌더, 승인 집계, repository/storage 인터페이스, 서비스와 FastAPI router factory를 둔다.
공유 스키마를 복제한 운영 모델을 만들지 않는다. DTO와 Protocol로 3번의 SQLAlchemy·세션·S3 구현을 주입한다.
fixture는 `backend/tests/role5/`에만 둔다. API fixture 응답에는 mode=fixture를 표시한다.

렌더는 JPEG/PNG 실제 디코딩, 25 MiB와 20 MP 제한, EXIF 방향·sRGB 변환·투명 배경 흰색 합성 후
원본에 Brightness → Color 순서로 적용한다. JPEG 품질 92, subsampling=0, EXIF 제거.
호출자가 넘기는 seekable stream과 임시 출력 파일을 사용해 원본 바이트의 중복 복사를 피한다.
저장은 사진별 잠금/트랜잭션 안에서 번호를 배정하고 `edits/{album_id}/{photo_id}/edit-N.jpg`에 저장한다.
원본과 parent 보정본은 수정하지 않는다. 재렌더에도 동일 render_edit 함수를 쓴다.

승인 대상은 현재 앨범 멤버 중 확정된 등장 멤버. uncertain/excluded는 제외한다.
분석 미완료·미등록/불확실 인물만 있는 사진은 승인 대상 없음 상태를 명시하며 자동 최종화하지 않는다.
사람 없는 사진은 분석 완료/face_count=0/shot_type=no_face일 때 업로더 승인(3번 확인 요청).
새 버전 승인 0, 중복 승인은 idempotent, 최종본은 조건 충족 버전 중 가장 큰 number 하나.
등장 인물/앨범 멤버 집합 변경 시 3번이 같은 사진 잠금 안에서 invalidate_approvals를 호출해 모든 버전 승인 삭제.
승인 취소는 해당 버전에서 즉시 반영. 최종 컬럼 없이 매번 현재 데이터로 집계한다.

## 작업 순서와 검증

1. [x] 렌더 테스트 → 실패 확인 → 구현 → 검사
   - 파일: backend/app/edits.py, backend/tests/role5/test_render.py.
   - 인터페이스: render_edit(source, destination, EditSettings) -> RenderResult.
   - 실 이미지 픽셀 밝기/흑백, SHA 원본 보존, EXIF 회전, 잘못된 형식·과대 픽셀·잘린 파일·NaN 설정 거부.
2. [x] 버전/승인 서비스 테스트 → 실패 확인 → 구현 → 검사
   - 파일: 동일 edits.py, backend/tests/role5/fixtures.py, test_service.py.
   - 인터페이스: EditService.create/list/approve/revoke, build_edit_router(service, current_member).
   - 다른 앨범/비등장 승인 거부, parent 다른 사진 거부, 저장 실패/DB rollback, 중복/동시 승인·버전 생성.
   - 인물 추가/제외/탈퇴/취소 전이, 다중 후보 중 최종본 하나, 재시작 후 파일 SHA와 설정 보존.
3. [x] API 계약 테스트 → 실패 확인 → 구현 → 검사
   - 파일: backend/tests/role5/test_api.py.
   - 4개 확정 endpoint, JSON 오류, UUID·설정 validation, 세션 주입 권한, provider/mode 보존.
   - 프리뷰/다운로드 endpoint 확장은 제안만 기록하고 확정 API를 임의 변경하지 않는다.
4. [x] 렌더 비교 및 통합 문서 작성, 이후 올라온 2번 기반에 EditorPanel 작성/fixture 검사
   - CSS saturate와 Pillow Color의 계수 차이를 수치 확인. 같다고 꾸미지 않고 2번에게 제안 전달.
   - frontend 기반 존재 시 frontend/src/editor/ 안에만 컴포넌트 구현. 없으면 계약·통합 예제를 인계.
   - docs/assembly/role-5.md에 완료/부분/미착수/미검증, 실제 검사 결과, 의존성과 요청 초안을 기록.
5. [ ] 전체 pytest·컴파일·의존성 검사·변경 diff 검토 후 사용자에게 커밋/push 승인 요청.

## 집중 검토

- 승인 대상 0명이 전원 승인으로 처리되는 오류.
- parent 설정을 원본이 아닌 보정본에 중첩 적용하는 오류.
- 인물 변경 후 예전 승인이 다시 유효해지는 오류.
- 저장 실패 뒤 DB 버전/고아 파일이 남거나 동시 저장이 파일을 덮어쓰는 오류.
- CSS 채도와 Pillow 채도를 같다고 표시하는 오류.

## 실행 기록

- 시작 검사 완료. 기존 실행 가능한 제품 코드/테스트 없음.
- 사용자 확정 계약을 설계로 사용하고 로컬에서 직접 구현한다. 별도 워크트리는 만들지 않는다.
- 원격 커밋/역할 PR 작성은 아직 수행하지 않았다. 이후 이슈 #3/#4/#7 및 2번 COMMENT 리뷰 게시.
- 렌더 단계 16개 → 서비스 포함 33개 → API 포함 43개 통과.
- 최종 회귀/색상 비교/공통 오류 핸들러 포함 48개, Python 3.13.15/3.14.7 모두 `pytest -q -W error` 통과.
- 독립 검토 두 지적(HTTPException 상태, CMYK ICC 입력 모드)을 실패 테스트로 재현 후 수정.
- 엄격 검사에서 fixture SQLite close 누수를 발견해 수정. 최종에는 경고 없음.
- 이후 프론트 기반 출현으로 frontend/src/editor/만 추가. React 프로젝트를 새로 만들지 않고 2번 lockfile snapshot에서 검사.
- EditorPanel 10개 테스트, TypeScript/Vite 빌드, 실제 Chrome 390px 저장→승인→취소 fixture 검사 완료.
- 결정: CSS/Pillow 차이는 단일 계수로 해결되지 않아 서버 권위 미리보기 계약을 3번 확인 대상으로 남김.
- 결정: 프로세스 강제 종료로 생길 수 있는 S3 고아 객체는 덮어쓰지 않고 보존/실패 처리. 운영 정리 어댑터는 3번 의존성.
