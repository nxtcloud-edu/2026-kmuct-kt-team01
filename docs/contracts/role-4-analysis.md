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
from app.quality import inspect_image
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

`members` 는 **dict 여도 되고 SQLAlchemy `Member` ORM 객체여도 된다.**
worker 가 ORM 객체를 그대로 넘기므로 지금 코드 그대로 동작한다.

기준 셀카를 찾는 순서:

| 순서 | 값 | 비고 |
|---|---|---|
| 1 | `reference_bytes` | raw bytes |
| 2 | `load_reference(reference_key)` | **권장.** `analyze(..., load_reference=storage.get)` |
| 3 | `reference_bucket` / `reference_s3` / 환경변수 `S3_BUCKET` + `reference_key` | S3 직접 참조 |

> **해결됨.** 3번이 `worker.analysis_members(members, storage)` 로 ORM Member 를
> `reference_bytes`(local) / `reference_s3`(S3) dict 로 바꿔 넘긴다(커밋 `fd67890`).
> 그 경로가 정식이다. `load_reference` 는 그 함수를 쓰지 않는 호출자를 위한 대안으로만 남긴다.

기준 얼굴 위치를 알 수 없거나, 로드에 실패하거나, 그 셀카에 얼굴이 없으면
**그 멤버만 건너뛰고** `skipped_members` 에 사유(`NO_REFERENCE` /
`NO_REFERENCE_BUCKET` / `REFERENCE_LOAD_FAILED` / `INVALID_PARAMETER`)를 남긴다.
사진 전체 분석은 계속된다.

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
- 연사 묶음과 대표 컷은 `worker.recompute_bursts`가 DB 트랜잭션 안에서 계산한다.
  촬영 시각이 있는 분석 완료 사진만 3초 창으로 묶으며, 시각이 없는 사진은
  `burst_group_id=None, is_best=True` 상태를 유지한다. `only_best=true`는 연사에서
  탈락한 컷만 제외한다.

## 7. mock 모드에서 화면 표시

`mode == "mock"` 이면 프론트가 "샘플 분석" 배지를 띄워야 한다.
mock 응답에는 `mock_source` 가 더 붙는다.

- `"manifest"` — 사람이 정답을 적어 넣은 등록 샘플
- `"synthetic"` — 등록되지 않은 사진. 얼굴마다 `synthetic: true`,
  `warnings` 에 "실제 얼굴 인식·인물 매칭이 아닙니다" 경고가 들어간다

mock 의 인물 매칭은 실제 인식 결과가 아니다. 정확도로 쓰지 않는다.

## 8. 여행 요약 (`app.insights`, T3 부가 기능)

```python
from app.insights import summarize_album
result = summarize_album(album_dict)
```

입력(3번이 집계해서 넘긴다. 사진 파일이나 파일명은 넘기지 않는다):

```python
{"name": "부산 여행", "photo_count": 4, "member_names": ["지민", "현우"],
 "photos": [{"id", "best_score", "shot_type", "tags", "captured_at", "is_best"}, ...]}
```

출력: `{summary_lines(3줄), highlights[{photo_id, reason}], provider, mode,
model_id, calls, elapsed_ms, usage, facts, warnings}`

- **Bedrock 호출은 앨범당 1회**다. 사진 수와 무관하다.
- **대표 사진 5장은 LLM 이 고르지 않는다.** `select_highlights()` 의 파이썬 규칙
  (분석 완료 + 연사 탈락 제외 → 장면 다양성 → 상대 점수)으로 고르고 `reason` 을 남긴다.
- `summary_lines` 는 **모델이 쓴 문장**이다. 사실 검증을 거치지 않았으므로 화면에
  "AI 요약"으로 표시한다. 프롬프트에서 집계 사실 밖 내용·고유 장소명을 금지했다.
- `SUMMARY_PROVIDER` 기본값은 `mock` 이고, mock 은 모델을 부르지 않고 집계 숫자로만
  문장을 만든다(지어낸 내용 없음). `off` 면 `summary_lines` 가 빈 배열이다.
- 오류 코드: `AWS_AUTH`(false) / `SUMMARY_MODEL_UNAVAILABLE`(false) /
  `SUMMARY_THROTTLED`(true) / `SUMMARY_TRUNCATED`(true) / `SUMMARY_INVALID`(true) /
  `SUMMARY_REFUSED`(false) / `SUMMARY_FAILED`(status>=500 이면 true)

| 환경변수 | 기본값 |
|---|---|
| `SUMMARY_PROVIDER` | `mock` (`bedrock` / `off`) |
| `BEDROCK_MODEL_ID` | `anthropic.claude-opus-5` |

**실제 Bedrock 호출은 아직 한 번도 하지 않았다.** 계정에서 이 모델 ID 에 접근 권한이
없으면 `SUMMARY_MODEL_UNAVAILABLE` 이 난다. 그때 `BEDROCK_MODEL_ID` 를 바꾼다.

## 9. 자연어 검색 구조화 (`app.insights.parse_search_query`, T3)

```python
parse_search_query("바다에서 찍은 단체샷", member_names=["지민", "현우"])
# -> {"tags": ["바다"], "shot_type": "group", "member_names": [], "only_best": False,
#     "understood": True, "query": ..., "provider": "mock", "mode": "mock",
#     "calls": {"bedrock_invoke": 0}, "elapsed_ms": 1, "model_id": None, "usage": None}
```

**구조화만 한다. 검색은 3번의 SQL 이 한다.** 임베딩 인프라를 만들지 않았다.

| 필드 | SQL 로 옮기는 법 |
|---|---|
| `tags` | AND 조건. `photos.tags` 에 전부 포함 |
| `shot_type` | `"any"` 면 조건을 걸지 않는다 |
| `member_names` | `photo_members` 조인. **앨범에 실제로 있는 이름만** 돌려준다 |
| `only_best` | `photos.is_best` 조건 추가 |
| `understood` | `False` 면 화면에 "검색어를 이해하지 못했습니다"를 띄운다 |

기본값(`SUMMARY_PROVIDER=mock`)은 모델을 부르지 않는 한국어 키워드 규칙 파서다.
`bedrock` 이면 enum 을 박은 구조화 출력으로 1회 호출한다. 어느 쪽이든 허용 목록 밖
태그와 앨범에 없는 사람 이름은 버린다.

## 10. 미등록 인물 그룹 (`app.facegroups`, T3)

```python
from backend.app.facegroups import faces_from_analysis, group_faces, make_rekognition_comparer

faces = faces_from_analysis(photo.id, photo.s3_key, analysis_result)   # status=="unregistered" 만
compare = make_rekognition_comparer(storage.get)
result = group_faces(all_faces, compare)
# -> {"groups": [{group_id, face_ids, representative, labeled_member_id}],
#     "ungrouped": [...], "comparisons": 12, "truncated": False, "failures": [], "threshold": 92.0}
```

- `face_id` 는 `"<photo_id>:<face_index>"` 다. DB 에 쓰지 않으니 3번이 저장한다.
- 같은 사진 안의 두 얼굴은 같은 사람일 수 없으므로 비교하지 않는다.
- 임계 92.0 (등록 인물 매칭 90보다 보수적). 판단 불가면 묶지 않는다.
- `truncated=True` 면 비교 예산을 다 써서 남은 얼굴은 묶지 못한 것이다. 숨기지 않는다.
- 그룹 이름을 지어내지 않는다. `labeled_member_id` 는 사람이 채운다.
- 수정 연산은 전부 순수 함수: `merge_groups(groups, keep_id, merge_id)`,
  `split_group(groups, group_id, face_ids)`, `move_face(groups, face_id, target_group_id)`.
  오류는 `GROUP_NOT_FOUND` / `GROUP_LABEL_CONFLICT` / `GROUP_SPLIT_ALL` / `GROUP_SPLIT_EMPTY`.
- `FACE_PROVIDER=rekognition` 에서만 실제 비교가 된다. mock 에서는 comparer 를 만들 수 없다
  (`CONFIG_INVALID`). 가짜 그룹을 만들어 보여주지 않기 위해서다.

## 11. 의존성 (해결됨)

`requirements.txt` 는 3번 소유이고, 필요한 것이 이미 다 들어 있다:
`boto3`, `pillow`, `anthropic[bedrock]==1.7.0` (커밋 `fd67890`).

`anthropic` 은 `insights.py` 에서만 lazy import 한다. 설치하지 않아도
`analysis.py` / `quality.py` / `facegroups.py` 는 정상 동작하고,
요약·자연어 검색만 `DEPENDENCY_MISSING` 으로 실패한다.
