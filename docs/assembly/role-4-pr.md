# PR 본문 (역할 4) — 그대로 복사해서 쓰면 된다

- base: `main`
- head: `work/20260920/role-4`
- 제목: `역할 4: 사진 분석(Rekognition)·품질·메타데이터 + 여행 요약·검색·인물 그룹`
- Draft 로 연다. 검토자: y3rtcn (역할 3)

```bash
gh pr create --base main --head work/20260920/role-4 --draft \
  --title "역할 4: 사진 분석(Rekognition)·품질·메타데이터 + 여행 요약·검색·인물 그룹" \
  --body-file docs/assembly/role-4-pr.md --reviewer y3rtcn
```

---

## 문제와 결과

빈 저장소에 ZZIK의 사진 분석 계층을 구성했습니다. 업로드된 사진에서 얼굴을 찾아 등록된 기준 인물과 대조하고, 장면 태그·촬영 정보·품질 지표를 뽑아 3번의 worker가 그대로 저장할 수 있는 dict로 돌려줍니다. 단체샷 자동 분리와 베스트컷 추천에 필요한 값이 모두 여기서 나옵니다.

기본 실행은 `FACE_PROVIDER=mock`이며 모든 응답에 `mode="mock"`이 실려 화면이 "샘플 분석" 배지를 띄울 수 있습니다. `FACE_PROVIDER=rekognition`으로 두면 같은 코드가 실제 Rekognition을 호출합니다. **자동 폴백은 없습니다** — AWS 인증이 실패하면 mock 성공으로 바꾸지 않고 `AWS_AUTH`로 실패합니다.

오분류가 데모에서 가장 치명적이라고 보고, 애매하면 배정하지 않는 쪽으로 만들었습니다. 1위 유사도가 90 미만이거나 1·2위 차이가 5 미만이면 `uncertain`으로 두고 사람 판단에 맡깁니다.

## 기능별 커밋

- `f61648c` — Rekognition 얼굴/장면/품질 분석 모듈과 mock 제공자
- `7d72312` — Bedrock 앨범 여행 요약과 규칙 기반 대표 사진 선정
- `61ffc18` — 3번 worker·API 실제 호출 계약에 맞춰 연결
- `d13ef63` — 자연어 검색어를 SQL 필터로 구조화
- `0bf49e7` — 미등록 인물 얼굴 그룹 생성·병합·분리

## 검증

```
.venv/Scripts/python -m pytest tests -q
140 passed, 1 warning in 5.70s
```

저장소 전체 테스트입니다. 3번의 `test_api.py` / `test_worker.py` / `test_models.py` / `test_storage.py`도 함께 통과합니다.

- 정상 / 얼굴 없음 / 얼굴 여러 개 / 미등록 인물 / 분석 실패 경로를 각각 검사
- AWS 예외 7종의 `retryable` 구분과 인증 오류 메시지 마스킹 검사
- DB·S3·AWS를 전혀 호출하지 않습니다. 공유 RDS와 데모 데이터를 건드리지 않았습니다
- 샘플 이미지는 Pillow로 그 자리에서 만드는 합성 이미지이며 저장소에 실사진이 없습니다

## 검증하지 않은 것

- **실제 Rekognition 호출 0회.** 개발 PC에 AWS 자격증명이 없어 전부 가짜 클라이언트로 검사했습니다. 실사진 정확도·비용·처리량은 **미측정**이며 similarity 점수를 정확도로 쓰지 않았습니다.
- **실제 Bedrock 호출 0회.** 계정에 `anthropic.claude-opus-5` 접근 권한이 있는지도 확인하지 못했습니다.
- **얼굴 그룹의 실제 묶음 정확도 미측정.** 주입한 비교 함수로만 검사했습니다.
- PostgreSQL이 아닌 SQLite 기준입니다(3번의 기존 조건과 동일).

## 연동 요청 (역할 3)

1. **`worker.py`에서 `analyze(..., load_reference=storage.get)`를 넘겨 주세요.** 지금은 `STORAGE_BACKEND=local`일 때 기준 셀카를 읽을 경로가 없어 모든 멤버가 `NO_REFERENCE_BUCKET`으로 건너뛰어집니다(= 인물 매칭 0건). `worker.py`는 역할 3 소유라 제가 고치지 않았습니다.
2. **`tests/test_api.py` 변경 확인 필요.** `test_reference_endpoint_reports_missing_role_four_dependency`가 `analysis.py` 부재를 전제로 503을 기대하고 있었습니다. 모듈이 생겨 200이 되므로, 부재 상황을 monkeypatch로 주입해 503 검사를 그대로 살리고 연결된 정상 경로 테스트를 따로 추가했습니다. 의도를 바꾸지 않았는지 확인해 주세요.
3. **`requirements.txt`에 `anthropic[bedrock]` 추가 여부 결정.** T3 요약·자연어 검색에만 필요합니다. 없어도 analysis/quality/facegroups는 정상 동작하고 요약만 `DEPENDENCY_MISSING`으로 실패합니다.
4. **연사 그룹화 중복 확인.** `worker.recompute_bursts`와 `quality.group_bursts`가 같은 일을 합니다. 역할 3 것이 이미 DB에 붙어 동작하므로 그대로 두고 제 함수는 남겨만 뒀습니다. 정리 여부를 알려 주세요.

## 인터페이스 요약

```python
validate_reference(image_bytes) -> {provider, mode, face_count}
    # 얼굴 0개 -> AnalysisError("NO_FACE"), 2개 이상 -> AnalysisError("MULTIPLE_FACES")

analyze(image_bytes, album_id, members, *, load_reference=None) -> {
    faces, face_count, shot_type, tags, quality, best_score,
    provider, mode, calls, elapsed_ms,
    matched_member_ids, skipped_members, warnings, image, capture }
```

`faces[].status`는 `matched` / `uncertain` / `unregistered` 셋 중 하나입니다. **`matched`만 `photo_members`에 넣으면 됩니다.** `face_count == 0`은 분석 실패가 아니라 `shot_type == "no_face"`입니다. 실패는 예외로만 옵니다.

전체 계약과 입출력 예시는 `docs/contracts/role-4-analysis.md`에 있습니다. 상세 상태는 `docs/assembly/role-4.md`에 기록했습니다.

실제 Rekognition·Bedrock 호출 검증 전까지 Draft를 유지합니다.
