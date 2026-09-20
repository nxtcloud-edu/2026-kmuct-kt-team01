# 역할 4 (AI·메타데이터·품질) 인계 기록

담당: jooya38 / 갱신: 2026-09-20 (세션 1)

## 현재 단계

분석 모듈 1차 구현 완료, **로컬 커밋만 존재. push·PR 없음.**

## 막힌 것 — 사람이 해줘야 진행됨

| 항목 | 상태 |
|---|---|
| `[REPO]` `[BASE]` `[RUN]` `[IAM]` 실제 값 | **미확정.** 역할 프롬프트에 대괄호 그대로 들어왔다 |
| `git remote origin` | **없음.** `git remote -v` 비어 있음 |
| `gh` 로그인 | **안 됨.** `gh auth status` → not logged into any GitHub hosts |
| 1번의 초기 커밋(루트) | 원격이 없어 확인 불가 |

그래서 아래를 **하지 않았다**: push, Draft PR 생성, 이슈 생성, 교차 검토 요청.
규칙대로 각자 다른 루트 커밋을 원격에 만들지 않았다. 로컬 브랜치 커밋만 남겨
1번의 루트 커밋이 나오면 그 위로 cherry-pick 해 올릴 수 있게 해뒀다.

로컬 브랜치: `work/local/role-4` (RUN 확정되면 `work/[RUN]/role-4` 로 rename)

## 한 일

| 기능 | 상태 |
|---|---|
| `validate_reference` (NO_FACE / MULTIPLE_FACES 코드 분리) | 완료·mock/가짜클라이언트로 검증 |
| `analyze` DetectFaces(ALL) → CompareFaces → DetectLabels 순서 | 완료·검증 |
| 얼굴 0개면 CompareFaces 미호출 | 완료·검증 |
| IoU ≥ 0.4 박스 대응 | 완료·검증 |
| 1위≥THRESHOLD & 1위-2위≥MARGIN 일 때만 확정, 아니면 uncertain | 완료·검증 |
| 같은 member_id 중복 배정 방지 (그리디) | 완료·검증 |
| matched / uncertain / unregistered 구분 | 완료·검증 |
| 라벨 9종 한글 태그 매핑, 미지원 라벨 폐기 | 완료·검증 |
| shot_type / sharpness / brightness / eyes_open_ratio / best_score | 완료·검증 |
| 입력 제한(5MB 축소·최소 80px·JPEG/PNG) + 축소 경고 기록 | 완료·검증 |
| AWS 예외 → AnalysisError(retryable 구분), 인증 메시지 통일·원문 비노출 | 완료·검증 |
| 인증 실패를 mock 성공으로 바꾸지 않음 | 완료·검증 |
| mock 모드(해시 시드, manifest, mode='mock', synthetic 표시) | 완료·검증 |
| EXIF 촬영시각·GPS, 없으면 null (추측 안 함) | 완료·검증 |
| 연사 그룹화 + 대표 컷 `group_bursts` | 완료·검증 |
| 3번용 계약 문서 `docs/contracts/role-4-analysis.md` | 완료 |
| Bedrock 여행 요약 (8-a) `app/insights.py` | **부분** — 코드·가짜클라이언트 검증 완료, 실제 Bedrock 호출 **미검증** |
| 자연어 검색 구조화 (8-b) | **미착수** |
| 미등록 얼굴 그룹 생성·병합·분리 (8-c) | **미착수** |
| 실제 Rekognition 호출 | **미실행** (아래) |
| worker 중단·재시도·수동수정 보존 공동 검사 (9) | **미착수** — 3번 worker 필요 |

## 실행한 검사

```
python -m pytest backend/tests -q
91 passed in 7.78s          # 2026-09-20, Python 3.13.5, Windows
```

- `backend/tests/test_analysis.py` — 제공자 설정, validate_reference 3종,
  호출 순서, 매칭 판정(확정/모호/임계미달/IoU미달/중복), 태그, 오류 변환 7종,
  멤버 스킵, mock 결정성·manifest
- `backend/tests/test_quality.py` — 이미지 검사·축소, IoU, 태그, 품질 공식,
  EXIF 유/무, 연사 그룹화
- `backend/tests/test_contract_examples.py` — 3번이 받을 응답·오류 형태
- `backend/tests/test_insights.py` — 대표 사진 선정 규칙, 집계 사실, mock/off,
  Bedrock 요청 인자·응답 파싱·오류 변환(가짜 클라이언트)

테스트는 DB·S3·AWS 를 전혀 쓰지 않는다. 공유 RDS 와 데모 데이터를 건드리지 않았다.
샘플 이미지는 Pillow 로 그 자리에서 만든 합성 이미지(단색)이고 저장소에 실사진이 없다.

## 측정하지 않은 것 (미측정)

- **실사진 인식 정확도** — 실제 Rekognition 을 한 번도 호출하지 않았다.
  AWS 자격증명이 이 개발 PC에 없고, EC2 인스턴스 역할 권한은 1번이 확인 중이다.
  테스트는 전부 가짜 클라이언트다. similarity 수치를 정확도로 쓰지 않는다.
- **비용·처리량** — 사진 1장당 호출 수는 `calls` 로 노출되지만(멤버 N명이면
  DetectFaces 1 + CompareFaces N + DetectLabels 1) 실제 요금·초당 처리량은 미측정.
- **2000장 처리** — 시도하지 않았다.
- **Bedrock 여행 요약의 실제 호출** — 한 번도 실행하지 않았다. 계정에 
  `anthropic.claude-opus-5` 접근 권한이 있는지도 확인하지 못했다.
  요약 문장 품질·요금 역시 미측정.

## 파일 소유권 관련 메모

- 역할표에 없던 파일 3개를 새로 만들었다. 전부 역할 4 소유로 둔다:
  `backend/app/insights.py` (T3 요약), `backend/app/__init__.py` (빈 파일),
  `backend/.gitignore` (`__pycache__` 제외). 3번이 다른 위치를 원하면 옮겨도 된다.
- 남의 소유 파일은 건드리지 않았다. `requirements.txt` 는 3번에게 요청 사항으로만 남겼다.

## 남은 일 / 의존성

1. `[RUN]`·origin 확정 → 브랜치 rename, push, Draft PR, 3번에게 리뷰 요청
2. 3번: `backend/requirements.txt` 에 `boto3`, `Pillow` 추가 (내 소유 파일 아님)
3. 1번: EC2 인스턴스 역할의 Rekognition 호출 권한 확인 결과 공유
   → 확인되면 `FACE_PROVIDER=rekognition` 으로 실사진 1장 실호출 검증
4. 3번 worker 가 생기면 재시도·수동수정 보존 공동 검사
5. 여유 생기면 Bedrock 여행 요약(8-a)

## 미처리 요청

없음. 받은 요청도 보낸 요청도 없다 (통신 채널인 GitHub 저장소가 아직 없음).
