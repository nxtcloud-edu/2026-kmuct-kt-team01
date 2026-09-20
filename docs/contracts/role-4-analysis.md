# 역할 4 → 역할 3 인터페이스: 사진 분석

작성: jooya38 (역할 4, AI·메타데이터·품질)
대상: 역할 3 (백엔드·worker)
파일: `backend/app/analysis.py`, `backend/app/quality.py`

이 모듈은 **DB·S3·API·worker 를 건드리지 않는다.** 바이트를 받아 dict 를 돌려줄 뿐이다.
저장·트랜잭션·재시도는 전부 3번이 한다.

---

## 1. import

```python
from app.analysis import analyze, validate_reference, AnalysisError
from app.quality import inspect_image, group_bursts      # 선택
```

## 2. 환경변수

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `FACE_PROVIDER` | `mock` | `rekognition` 또는 `mock`. **자동 폴백 없음** |
| `AWS_REGION` | `us-east-1` | boto3 에 region_name 만 넘긴다. 키는 넣지 않는다 |
| `SIMILARITY_THRESHOLD` | `90.0` | 인물 확정 임계 |
| `CANDIDATE_MARGIN` | `5.0` | 후보 확장 폭 겸 1·2위 최소 격차 |
| `MOCK_MANIFEST_PATH` | `backend/samples/mock_manifest.json` | mock 정답 manifest |
| `MOCK_SYNTHETIC_MATCH` | `1` | mock 에서 등록 안 된 사진에 합성 인물을 붙일지 |
| `S3_BUCKET` | (없음) | member 에 bucket 을 직접 주지 않을 때의 대체값 |

`FACE_PROVIDER` 에 다른 값이 오면 조용히 mock 으로 떨어지지 않고 `CONFIG_INVALID` 로 실패한다.

## 3. `validate_reference(image_bytes) -> dict`

셀카 업로드(`POST /api/members/me/reference`)에서 S3 저장 **전에** 부른다.

```python
{"provider": "rekognition", "mode": "live", "face_count": 1, "elapsed_ms": 231}
```

실패는 예외로 온다. 두 경우의 **코드가 다르다**:

| 상황 | code | retryable |
|---|---|---|
| 얼굴 0개 | `NO_FACE` | false |
| 얼굴 2개 이상 | `MULTIPLE_FACES` | false |

## 4. `analyze(image_bytes, album_id, members) -> dict`

`members` 는 기준 얼굴이 등록된 멤버만 넘기면 된다. 각 항목:

```python
{"id": "<member uuid>",
 # 아래 중 하나로 기준 셀카 위치를 알려준다
 "reference_bytes": b"...",                                  # 또는
 "reference_bucket": "kmu-proj-06-zzik", "reference_key": "refs/m1.jpg",   # 또는
 "reference_s3": {"bucket": "...", "key": "..."}}
```

기준 얼굴 위치를 알 수 없거나 그 셀카에 얼굴이 없으면 **그 멤버만 건너뛰고**
`skipped_members` 에 사유를 남긴다. 사진 전체 분석은 계속된다.

### 실제(rekognition) 응답 예 — 단체샷 2명, 한 명은 눈 감음

```json
{
  "faces": [
    {"box": {"left": 0.1, "top": 0.2, "width": 0.15, "height": 0.2},
     "member_id": "member-a", "similarity": 97.4, "uncertain": false,
     "detection_confidence": 99.5, "status": "matched"},
    {"box": {"left": 0.55, "top": 0.22, "width": 0.14, "height": 0.19},
     "member_id": "member-b", "similarity": 95.1, "uncertain": false,
     "detection_confidence": 99.5, "status": "matched"}
  ],
  "face_count": 2,
  "shot_type": "group",
  "tags": ["바다"],
  "quality": {"sharpness": 75.0, "brightness": 70.0, "eyes_open_ratio": 0.5},
  "best_score": 64.5,
  "provider": "rekognition",
  "mode": "live",
  "calls": {"detect_faces": 1, "compare_faces": 2, "detect_labels": 1, "total": 4},
  "elapsed_ms": 412,
  "matched_member_ids": ["member-a", "member-b"],
  "skipped_members": [],
  "warnings": [],
  "image": {"mime": "image/jpeg", "width": 640, "height": 480, "byte_size": 5428,
            "content_hash": "b803575e64c3b6be...", "downscaled_for_analysis": false},
  "capture": {"captured_at": null, "captured_at_source": null, "gps": null,
              "place": null, "place_reason": "REVERSE_GEOCODING_NOT_CONFIGURED",
              "notes": ["EXIF 정보 없음"]}
}
```

계약에 있던 10개 키(`faces` … `elapsed_ms`)는 항상 들어 있다.
그 아래 `matched_member_ids` / `skipped_members` / `warnings` / `image` / `capture` 는
**추가로 주는 정보**다. 저장 여부는 3번이 정한다. 응답 전체는 JSON 직렬화가 된다.

### DB 컬럼 대응 (제안)

| 컬럼 | 값 |
|---|---|
| `photos.face_count` | `face_count` |
| `photos.shot_type` | `shot_type` |
| `photos.tags` | `tags` |
| `photos.quality` | `quality` |
| `photos.best_score` | `best_score` |
| `photos.provider` / `mode` | `provider` / `mode` |
| `photos.captured_at` | `capture.captured_at` (없으면 NULL. 추측하지 않는다) |
| `photos.width/height/mime/byte_size/content_hash` | `image.*` (업로드 시 `inspect_image` 로 먼저 구해도 됨) |
| `photo_members` | `faces` 중 `status == "matched"` 인 것만. `source='auto'` |

**`status != "matched"` 인 얼굴은 photo_members 에 넣지 않는다.**

| `status` | 뜻 | 화면 |
|---|---|---|
| `matched` | 확정 | 인물 태그 표시 |
| `uncertain` | 후보는 있으나 1·2위가 붙어 확정 못 함 (`candidates` 동봉) | "확인 필요" 로 두고 수동 지정 유도 |
| `unregistered` | 등록된 기준 인물 중 후보조차 없음 = 미등록 인물 | "미등록 인물" |

`face_count == 0` 이면 `shot_type == "no_face"` 이고 `faces` 는 빈 배열이다.
이건 **분석 실패가 아니다.** 실패는 예외로만 온다(`analysis_status='failed'`).

### 재분석 시 수동 수정 보존

`analyze()` 는 `source='auto'` 결과만 만든다. `POST /api/photos/{id}/reanalyze` 에서
`photo_members.source='manual'` 행은 3번이 지워선 안 된다. 이 모듈은 DB를 모른다.

## 5. `AnalysisError(code, message_ko, retryable)`

`err.to_dict()` 가 공통 오류 형식 그대로다:

```json
{"code": "NO_FACE", "message": "사진에서 얼굴을 찾지 못했습니다...", "details": {"retryable": false}}
```

| code | retryable | 의미 |
|---|---|---|
| `NO_FACE` / `MULTIPLE_FACES` | false | 기준 셀카 검증 실패 |
| `AWS_AUTH` | false | 권한·자격증명. 메시지는 항상 "AWS 분석 권한을 확인해 주세요" (원문 비노출) |
| `AWS_THROTTLED` | **true** | 스로틀링 → worker 가 재시도 |
| `AWS_UNAVAILABLE` | **true** | 연결 실패·타임아웃·InternalServerError → 재시도 |
| `INVALID_IMAGE` / `UNSUPPORTED_FORMAT` / `IMAGE_TOO_LARGE` / `IMAGE_TOO_SMALL` | false | 입력 문제 |
| `CONFIG_INVALID` | false | 환경변수 문제 |
| `ANALYSIS_FAILED` | false | 그 외 |

**worker 는 `retryable` 만 보고 재시도하면 된다.** `AWS_AUTH` 를 재시도하지 마라.
`photos.analysis_error` 에는 `code` 를 넣는 것을 권한다(사용자에겐 `message`).

## 6. 보조 함수 (`app.quality`)

- `inspect_image(bytes) -> ImageInfo(mime, width, height, byte_size, content_hash)`
  업로드 검증·저장에 바로 쓸 수 있다. JPEG/PNG 아니면 `UNSUPPORTED_FORMAT`.
- `extract_capture_metadata(bytes)` — EXIF 촬영시각·GPS. 없으면 `null`. 추측하지 않는다.
  장소 이름은 외부 조회 설정이 없어 항상 `null` (`place_reason`).
- `group_bursts(items, window_seconds=3.0)` — 연사 묶음과 대표 컷.
  입력 `[{id, captured_at?, created_at?, best_score}]`,
  출력 `{photo_id: {"burst_group_id": str|None, "is_best": bool}}`.
  묶이지 않은 단독 사진은 `burst_group_id=None, is_best=True` 다
  (→ `only_best=true` 필터가 "연사에서 탈락한 컷"만 걸러낸다).
  DB 에 쓰지 않는다. 앨범 단위로 3번이 호출해 저장한다.

## 7. mock 모드에서 화면 표시

`mode == "mock"` 이면 프론트가 "샘플 분석" 배지를 띄워야 한다.
mock 응답에는 `mock_source` 가 더 붙는다.

- `"manifest"` — 사람이 정답을 적어 넣은 등록 샘플
- `"synthetic"` — 등록되지 않은 사진. 얼굴마다 `synthetic: true`,
  `warnings` 에 "실제 얼굴 인식·인물 매칭이 아닙니다" 경고가 들어간다

mock 의 인물 매칭은 실제 인식 결과가 아니다. 정확도로 쓰지 않는다.

## 8. 3번에게 필요한 것 (REQUESTED)

`backend/requirements.txt` 는 3번 소유다. 이 모듈은 다음이 필요하다:

```
boto3        # 로컬 검증 버전 1.43.98
Pillow       # 로컬 검증 버전 12.2.0
```
