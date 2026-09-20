# ROLE-05 통합 계약 · 2/3번 인계

이 문서는 로컬 구현의 **통합 제안**이다. 팀 공통 계약을 변경하거나 다른 담당자와 합의 완료한 것으로 취급하지 않는다.
BASE=main / RUN=20260920 확인. 역할 3의 새 기반 aac5017과 역할 2의 5213e68을 읽고 연결 차이를 기록했다.
현재 요청: [#3 서버 연결](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/3),
[#4 업로드 원본 보존](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/4),
[#7 편집 패널 연결](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/7).

## 3번: 공통 서버에 연결

운영 코드: `backend/app/edits.py`. 공통 모델·migration·운영 requirements는 만들지 않았다.
`EditService(repository, storage)`와 `build_edit_router(service, current_member)`를 제공한다.

```python
from typing import Annotated
from fastapi import Depends
from backend.app.api import current_member
from backend.app.models import Member
from backend.app.edits import EditService, build_edit_router

# repository/storage: 아래 Protocol을 구현하는 3번의 운영 어댑터 인스턴스.
# 3번의 current_member는 Member 객체이므로 id만 전달하는 bridge.
def current_member_id(member: Annotated[Member, Depends(current_member)]) -> str:
    return member.id

service = EditService(repository, storage)
app.include_router(build_edit_router(service, current_member_id))
```

router에 `/api`가 이미 포함된다. 3번 api.py의 동일 경로 501 handler를 먼저 제거/위임해야 한다.
동일 endpoint를 중복 등록하면 기존 501이 먼저 선택될 수 있다. 앱 생성·CORS·쿠키 발급·인증을 중복 구현하지 않는다.
기존 HTTPException(401/403 등)의 상태와 헤더를 보존하면서 공통 JSON 오류로 응답한다.
앱에 등록된 ApiError 등 구체적인 예외 핸들러에도 처리를 위임한다.
테스트의 `X-Fixture-Member` 헤더는 테스트 전용이며 운영 인증으로 사용할 수 없다.

### Repository 어댑터 요구

- `mode="live"`. fixture 저장소는 테스트 폴더에만 있고 `mode="fixture"`로 표시된다.
- `transaction(photo_id)`는 SQLAlchemy Session과 실제 commit/rollback을 소유한다.
- 사진 행 `SELECT ... FOR UPDATE` 후 PhotoSnapshot·edits·approvals를 읽는다.
- PhotoSnapshot은 ORM 모델이 아닌 읽기 DTO. 기존 스키마의 값을 매핑한다.
- `active_member_ids`: 이 앨범의 현재 유효 멤버 ID 집합.
- `confirmed_member_ids`: excluded=false이면서 확정된 멤버만. uncertain을 여기에 넣지 않는다.
- `has_unresolved_faces`: 미등록/불확실 얼굴 존재 여부. 기본 True이므로 어댑터가 확인 후 False를 명시해야 승인 가능.
  이 정보의 스키마 매핑은 3·4번이 결정한다. face_count와 고유 멤버 수만 비교해서 임의 판단하지 않는다.
- `provider`, `mode`는 photos 값을 유지한다. 모든 버전 응답에도 포함된다.
- `edits()`는 EditRecord 목록, `approvals()`는 `{edit_id: set(member_id)}`를 반환한다.
- `add_edit()`는 계약의 edits 컬럼에 설정을 저장한다. created_at은 ISO UTC 문자열 ↔ DB datetime으로 변환한다.
- `add_approval()`는 UNIQUE(edit_id,member_id)에 대해 중복을 no-op 처리한다. created_at은 DB 또는 어댑터가 설정한다.
- `remove_approval()`는 지정된 본인의 승인만 삭제한다. `clear_approvals()`는 현재 사진의 모든 버전 승인만 삭제한다.
- `photo_id_for_edit(edit_id)`가 반환한 사진에서도 트랜잭션 안에서 버전 존재와 앨범 권한을 다시 검사한다.
- 버전 번호는 잠금 안에서 max(number)+1로 배정한다. UNIQUE(photo_id,number)는 유지한다.

### 승인 상태 전이 — 확인 요청

| 상황 | 로컬 구현의 제안 규칙 |
|---|---|
| 확정 인물 사진 | 현재 확정된 등장 멤버 전원 명시적 승인 |
| 분석 미완료/실패 | 저장은 가능, 승인/최종본 차단 |
| 불확실·미등록 얼굴이 남음 | 승인/최종본 차단, 인물 확인 요청 |
| 사람이 없는 사진 | done + no_face + face_count=0 + 불확실 없음일 때 업로더 승인 |
| 사람 없는 사진의 업로더 탈퇴 | 승인 대상 없음, 최종본 없음 |
| 새 버전 | 항상 승인 0개 |
| 여러 버전 전원 승인 | 가장 큰 number의 버전 하나만 is_final=true |
| 최신 최종본 승인 취소 | 해당 버전 해제. 과거 승인 충족 버전이 있으면 그것을 선택 |
| 등장 인물 추가/제외, 멤버 탈퇴, 확정 상태 변경 | 아래 hook으로 모든 버전의 승인을 영구 삭제 후 재승인 |
| 같은 인물/확정 상태 그대로 재분석 | 승인을 유지할 수 있음 |

인물 수동 수정/분석 결과 반영/탈퇴 handler는 **같은 트랜잭션**에서:

```python
from app.edits import invalidate_approvals

with repository.transaction(photo_id) as tx:
    # 역할 3의 ORM으로 인물/멤버 상태를 변경하고 실제 변경 여부 판단.
    # 변경된 경우, commit 전에:
    invalidate_approvals(tx)
```

앨범 멤버 변경은 영향받는 사진들을 ID 순서로 잠근다. 다른 트랜잭션으로 승인 삭제를 분리하면
사진 수정과 동시 승인 사이에 경쟁 상태가 생긴다. runtime 집계만으로는 기존 승인 부활을 막을 수 없다.
이 hook 연결 전에는 인물 변경 후 최종본 해제 기능이 운영에서 완료된 것이 아니다.
DB `final` 컬럼·순환 FK·좋아요 집계는 사용하지 않는다.

### S3 저장과 다운로드

- `open_original(photo)`는 원본 S3 객체를 seek 가능한 임시 파일로 내려받아 context manager로 제공한다.
  원본 바이트를 메모리에 여러 벌 담지 않고, 내려받는 과정에서도 25 MiB 초과를 차단한다.
- `write_edit(key, stream)`는 비공개 JPEG를 완전히 저장한 뒤 반환한다.
  `IfNoneMatch='*'` 등으로 기존 객체 덮어쓰기를 거부한다. 실패 시 부분 객체는 어댑터가 처리한다.
- 경로: `edits/{album_id}/{photo_id}/edit-N.jpg`. 업로드된 원본 키/사용자 파일명은 경로 조합에 쓰지 않는다.
- `delete_edit(key)`는 DB 저장 실패 시 방금 생성한 보정 객체만 보상 삭제한다.
- 프로세스 강제 종료·S3 응답 유실·DB commit 결과 불명확 등 분산 저장 장애는 fixture로 증명되지 않는다.
  고아 객체는 재시도 시 덮어쓰지 않고 실패한다. DB 참조 여부 확인 후 3번의 정리 절차가 필요하다.
- 원본 다운로드는 기존 `GET /api/photos/{id}/download` 동작을 보존한다.
  보정본 다운로드 선택과 인증된 미리보기 URL 제공은 3번의 API 결정이 필요하다. endpoint를 임의 추가하지 않았다.
- 승인된 버전을 내려줄 경우: 같은 잠금 안에서 `service.list()`의 규칙과 일치하게 final_edit_id를 계산하고
  그 버전 number의 `edit_key(photo, number)`를 사용한다. 잠금 중 service.list()를 중첩 호출하지 않는다.
  미리보기와 다운로드는 이 저장 객체를 공유하거나 동일 `render_edit`에 원본과 전체 설정을 전달한다.

### 메모리·렌더 규칙

25 MiB / 20,000,000 pixels, 실제 JPEG/PNG만, APNG 거부. EXIF 방향 적용, 내장 ICC→sRGB,
알파는 흰색에 합성, Brightness→Color 순서, JPEG quality=92/subsampling=0, EXIF/GPS 제거.
픽셀 제한은 보정 한도이며 공통 업로드 한도 변경은 아니다.
프로세스당 동시 렌더 1개로 제한한다. 2GB EC2에서는 서버 프로세스 수·분석 worker 메모리도 1번과 함께 확인해야 한다.
메모리 성능/실사진 대량 처리량은 미측정이다.

## 2번: EditorPanel 연결

2번의 frontend 기반을 확인한 후 `frontend/src/editor/`에만 컴포넌트를 구현했다.
공통 App.tsx/package.json/lockfile/styles는 수정하지 않았다. 공개 props:
`<EditorPanel photoId originalUrl members onSaved />`.
`members`는 `{id,display_name}[]`, `onSaved`는 `() => void`이다.
컴포넌트 import: `import EditorPanel from './editor/EditorPanel'` (연결 파일 위치에 맞춰 상대경로 조정).
2번 snapshot에서 10개 테스트/TypeScript/Vite 빌드, Chrome 모바일 fixture 조작을 확인했다.
동일 사진의 협업 상태는 멤버 ID 변경·창 focus·visible 10초 간격·수동 새로고침으로 갱신된다.

현재 확정 경로의 로컬 응답:

| 요청 | 결과 |
|---|---|
| POST /api/photos/{id}/edits | 201, 저장 버전 객체 |
| GET /api/photos/{id}/edits | 200, `{photo_id, versions, final_edit_id, provider, mode, storage_mode}` |
| POST /api/edits/{id}/approve | 200, 해당 버전의 갱신된 객체 |
| DELETE /api/edits/{id}/approve | 200, 해당 버전의 갱신된 객체 |

```json
{
  "id": "27ccdbef-a78f-4c7b-b66a-4b0121bb3e92",
  "photo_id": "90bb8450-6a7e-4a6b-a00c-1a8d6f70d136",
  "author_member_id": "b8ea92b4-958b-4779-94b7-3d2fd116b047",
  "parent_id": null,
  "number": 1,
  "created_at": "2026-09-20T00:00:00+00:00",
  "brightness": 1.0,
  "saturation": 1.0,
  "approval_count": 0,
  "required_count": 1,
  "required_member_ids": ["b8ea92b4-958b-4779-94b7-3d2fd116b047"],
  "approved_member_ids": [],
  "is_final": false,
  "can_approve": true,
  "approved_by_me": false,
  "approval_blocked_reason": null,
  "provider": "fixture",
  "mode": "fixture",
  "storage_mode": "fixture"
}
```

위 JSON은 계약 예시이며 실제 사용자 활동이 아니다. 버전 목록은 number 내림차순이다.
작성자 표시는 members에서 author_member_id로 조회한다. 누락된 작성자는 ID 대신 ‘탈퇴한 멤버’ 등으로 표시한다.
선택 버전의 brightness/saturation을 슬라이더에 복원하고 id를 parent_id로 보내 새 버전을 저장한다.
빈 목록, 저장 중 중복 클릭 방지, 실패 재시도, 승인 취소, 누르는 동안 원본 보기, 모바일 터치 취소를 처리한다.
승인 변경 후 전체 목록을 다시 받아 다른 버전의 is_final도 갱신한다.
API는 상대경로 `/api`와 같은 origin 쿠키를 사용한다.

### CSS와 서버 미리보기 차이 — 해결 결정 필요

실제 렌더 테스트에서 brightness=1, saturation=0, 단색 RGB 입력 결과:

| 입력 | CSS saturate(0) 계산값 | Pillow JPEG 실측 |
|---|---|---|
| 빨강 (255,0,0) | 약 (54,54,54) | (76,76,76) |
| 초록 (0,255,0) | 약 (182,182,182) | (150,150,150) |

CSS는 약 0.213/0.715/0.072, Pillow Color는 약 0.299/0.587/0.114의 명도 계수를 사용한다.
단일 채도 배수 조정으로 모든 색의 차이를 없앨 수 없다. 이 결과는 합성 단색 검증이고 실사진 브라우저 육안 비교는 미검증이다.

권장 통합 제안: 슬라이더 중 CSS를 즉시 보여주되 근사 미리보기로 취급하고, 조작이 끝나면
동일 `render_edit`로 생성한 서버 이미지를 보여준다. 저장 버전·다운로드는 서버 객체로 통일한다.
서버 미리보기 경로 추가는 3번의 계약 결정이 필요하므로 아직 구현하지 않았다.
다른 선택은 2번이 Pillow 규칙과 같은 canvas 필터를 쓰는 것이지만 이것 역시 현재 CSS 계약 변경이다.

근거: [W3C Filter Effects](https://www.w3.org/TR/filter-effects-1/#funcdef-filter-saturate),
[Pillow ImageEnhance 구현](https://pillow.readthedocs.io/en/stable/_modules/PIL/ImageEnhance.html),
[Pillow Image 문서](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[FastAPI APIRoute 문서](https://fastapi.tiangolo.com/how-to/custom-request-and-route/).

## 요청 원안과 현재 처리

아래는 최초 요청 원안이다. 현재 backend-adapters/approval 정책은 #3, editor-base/preview 계약은 #7로 게시했다.
프론트 리뷰는 PR #2의 full SHA 기준 COMMENT로 게시했다. 원본 손실 문제는 별도 #4.
별도의 미게시 원안을 중복 이슈로 만들지 않는다. role-5 자체 head는 아직 미커밋 로컬 작업이다.

1. `ZZIK:<RUN>:role-5:backend-adapters`, to=role-3, kind=change.
   필요한 파일: 3번 소유 repository/storage/auth wiring 및 requirements.
   필요한 결과: 위 Protocol 구현, Pillow==12.3.0 호환성 반영, 네 endpoint 등록.
   수락 기준: `_test` PostgreSQL에서 잠금·동시 저장·rollback 검사, 비공개 S3 별도 테스트 prefix에서 원본/보정 SHA 보존.
2. `ZZIK:<RUN>:role-5:approval-transitions`, to=role-3, kind=decision.
   필요한 파일: 인물 수정/재분석/멤버 탈퇴 handler.
   필요한 결과: no_face 업로더 승인·불확실 차단·최대 number 최종본·과거 최종본 fallback 승인, 원자적 무효화 hook 연결.
   수락 기준: 인물 추가→기존 최종 해제→재승인, 탈퇴 후 재가입해도 옛 승인 부활 없음.
3. `ZZIK:<RUN>:role-5:preview-download-contract`, to=role-3, kind=decision.
   필요한 파일: 사진 미리보기/다운로드 API.
   필요한 결과: 서버 미리보기 URL/원본·보정본 다운로드 선택 계약 확정.
   수락 기준: UI 최종 미리보기와 다운로드가 같은 보정 객체, 원본 다운로드 해시 보존.
4. `ZZIK:<RUN>:role-5:editor-base`, to=role-2, kind=change.
   필요한 파일: 2번의 frontend 프로젝트 기반 및 Photo 상세 컴포넌트.
   필요한 결과: 실제 상세 화면에 EditorPanel mount와 원본 URL/상위 갱신 callback 연결.
   수락 기준: frontend/src/editor/ 연결 위치 확정, 모바일 화면에서 편집·저장·승인 흐름 검사.
5. `ZZIK:<RUN>:role-5:frontend-review`, to=role-2, kind=review.
   필요한 결과: 역할 PR 및 현재 full head SHA.
   수락 기준: 실제 diff를 읽고 접근성·API 계약·모바일 편집 흐름 검토를 tkdgur3207 계정에서 남김.
