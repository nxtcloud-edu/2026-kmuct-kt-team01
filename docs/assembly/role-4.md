# 역할 4 (AI·메타데이터·품질) 인계 기록

담당: jooya38 / 갱신: 2026-09-20 (세션 1)
브랜치: `work/20260920/role-4` (base `main`) / RUN `20260920`

## 현재 단계

분석·요약·검색·얼굴그룹 구현 완료, 3번 worker/API 계약에 연결해 저장소 전체 테스트 통과.
브랜치 push 완료. **PR 은 아직 열지 못했다** (아래 참고).

## 최근 커밋

| SHA | 내용 |
|---|---|
| `f61648c` | analysis.py / quality.py — Rekognition 분석 + mock 제공자 |
| `7d72312` | insights.py — Bedrock 여행 요약, 규칙 기반 대표 사진 |
| `61ffc18` | 3번 worker·API 실제 호출 계약에 연결 (ORM members, load_reference, 테스트 이전) |
| `d13ef63` | 자연어 검색어 → SQL 필터 구조화 |
| `0bf49e7` | 미등록 인물 얼굴 그룹 생성·병합·분리 |

## 막힌 것 — 사람이 해줘야 진행됨

| 항목 | 상태 |
|---|---|
| `gh` 로그인 | **안 됨** (`gh auth status` → not logged into any GitHub hosts). PR·이슈를 자동으로 못 연다. PR 본문은 `docs/assembly/role-4-pr.md` 에 준비해 뒀다 |
| 잘못 올라간 `origin/work/local/role-4` | RUN 확정 전에 올라간 브랜치다. 내용은 `work/20260920/role-4` 에 cherry-pick 으로 다 들어갔다. **삭제해도 되는지 확인 필요** (원격 브랜치라 임의로 지우지 않았다) |

## 한 일

| 기능 | 상태 |
|---|---|
| `validate_reference` (NO_FACE / MULTIPLE_FACES 코드 분리) | 완료·검증 |
| `analyze` DetectFaces(ALL) → CompareFaces → DetectLabels 순서 | 완료·검증 |
| 얼굴 0개면 CompareFaces 미호출 | 완료·검증 |
| IoU ≥ 0.4 박스 대응 | 완료·검증 |
| 1위≥THRESHOLD & 1위-2위≥MARGIN 일 때만 확정, 아니면 uncertain | 완료·검증 |
| 같은 member_id 중복 배정 방지 | 완료·검증 |
| matched / uncertain / unregistered 구분 | 완료·검증 |
| 라벨 9종 한글 태그 매핑, 미지원 라벨 폐기 | 완료·검증 |
| shot_type / sharpness / brightness / eyes_open_ratio / best_score | 완료·검증 |
| 입력 제한(5MB 축소·최소 80px·JPEG/PNG) + 축소 경고 | 완료·검증 |
| AWS 예외 → AnalysisError(retryable), 인증 메시지 통일·원문 비노출 | 완료·검증 |
| 인증 실패를 mock 성공으로 바꾸지 않음 | 완료·검증 |
| mock 모드(해시 시드, manifest, mode='mock', synthetic 표시) | 완료·검증 |
| EXIF 촬영시각·GPS, 없으면 null (추측 안 함) | 완료·검증 |
| 연사 그룹화 | `worker.recompute_bursts`를 정식 경로로 확정·검증 |
| **3번 worker ORM members 수용 + `load_reference` 훅** | 완료·검증 |
| Bedrock 여행 요약 (8-a) | **부분** — 가짜 클라이언트 검증 완료, 실제 Bedrock 호출 **미검증** |
| 자연어 검색 구조화 (8-b) | 완료 — 규칙 파서 검증 완료, bedrock 경로는 가짜 클라이언트만 |
| 미등록 인물 그룹 (8-c) | 완료 — 주입 비교 함수로 검증, 실제 Rekognition 묶기는 **미검증** |
| 실제 Rekognition 호출 | **미실행** |

## 실행한 검사

```
.venv/Scripts/python -m pytest tests -q
140 passed, 1 warning in 5.70s     # 2026-09-20, Python 3.13.5, Windows
```

저장소 전체 테스트다. 3번의 `test_api.py` / `test_worker.py` / `test_models.py` /
`test_storage.py` 도 같이 통과한다.

- `tests/test_analysis.py` — 제공자 설정, validate_reference 3종, 호출 순서,
  매칭 판정(확정/모호/임계미달/IoU미달/중복), 태그, 오류 변환 7종, 멤버 스킵,
  ORM 객체·로더 경로, mock 결정성·manifest
- `tests/test_quality.py` — 이미지 검사·축소, IoU, 태그, 품질 공식, EXIF 유/무
- `tests/test_contract_examples.py` — 3번이 받을 응답·오류 형태
- `tests/test_insights.py` — 대표 사진 선정, 집계 사실, mock/off, Bedrock 요청·응답·오류,
  자연어 검색 규칙 파서와 지어낸 태그/이름 제거
- `tests/test_facegroups.py` — 그룹 생성·예산·결정성·실패 처리, 병합/분리/이동 규칙, 크롭

DB·S3·AWS 를 전혀 쓰지 않는다. 공유 RDS 와 데모 데이터를 건드리지 않았다.
샘플 이미지는 Pillow 로 그 자리에서 만든 합성 이미지이고 저장소에 실사진이 없다.

## 측정하지 않은 것 (미측정)

- **실사진 인식 정확도** — 실제 Rekognition 을 한 번도 호출하지 않았다.
  이 PC 에 AWS 자격증명이 없고, EC2 인스턴스 역할 권한은 1번이 확인 중이다.
  테스트는 전부 가짜 클라이언트다. similarity 수치를 정확도로 쓰지 않는다.
- **비용·처리량** — 사진 1장당 호출 수는 `calls` 로 노출되지만(멤버 N명이면
  DetectFaces 1 + CompareFaces N + DetectLabels 1) 실제 요금·초당 처리량은 미측정.
- **2000장 처리** — 시도하지 않았다.
- **Bedrock 여행 요약·자연어 검색의 실제 호출** — 한 번도 실행하지 않았다.
  계정에 `anthropic.claude-opus-5` 접근 권한이 있는지도 확인하지 못했다.
- **얼굴 그룹의 실제 묶음 정확도** — 주입한 가짜 비교 함수로만 검사했다.

## 3번과의 연동 상태

3번이 `assemble/20260920` 에서 내 첫 두 커밋(`e7eb611`, `e460b70`)을 이미 가져갔고
`fd67890 feat(integration): connect role 4 analysis worker` 로 연결까지 끝냈다.
그래서 내가 보내려던 요청 4건 중 3건이 이미 해결됐다.

| 요청 | 상태 |
|---|---|
| 기준 셀카 로딩 경로 | **해결됨.** 3번이 `worker.analysis_members(members, storage)` 로 ORM Member 를 `reference_bytes`/`reference_s3` dict 로 바꿔 넘긴다. 내 `load_reference` 훅은 대안으로만 남긴다 |
| `requirements.txt` 의 `anthropic[bedrock]` | **해결됨.** 3번이 `anthropic[bedrock]==1.7.0` 추가 |
| `tests/test_api.py` | **해결됨.** 3번이 직접 `test_reference_endpoint_uses_role_four_mock_and_stores_reference` 로 고쳤다. 충돌을 없애려고 내 버전을 버리고 3번 것을 그대로 채택했다 |
| 연사 그룹화 중복 | **해결됨.** DB에 연결된 `worker.recompute_bursts`를 유지하고 미사용 `quality.group_bursts`는 조립 브랜치에서 제거했다. 촬영 시각이 없는 사진은 단독 베스트 상태를 유지한다 |

`61ffc18`, `d13ef63`, `0bf49e7`, `70b29cb`, `7ecbff6`은 `assemble/20260920`에 반영됐다.

## 파일 소유권 메모

역할표에 없던 파일을 새로 만들었다. 전부 역할 4 소유로 둔다:
`backend/app/insights.py`, `backend/app/facegroups.py`, `backend/samples/`,
`tests/conftest.py`, `tests/test_analysis.py`, `tests/test_quality.py`,
`tests/test_insights.py`, `tests/test_facegroups.py`, `tests/test_contract_examples.py`.

남의 소유 파일 중 건드린 것은 `tests/test_api.py` 하나이고 위 2번에 적었다.
`requirements.txt`, `models.py`, `worker.py`, `api.py` 는 건드리지 않았다.

## 미처리 요청

받은 요청 없음. 보낸 요청은 위 4건이며 `gh` 로그인이 되면 이슈로 등록해야 한다.
