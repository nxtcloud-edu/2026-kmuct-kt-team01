# ZZIK 팀 설정

## 실행 값

| 항목 | 값 | 상태 |
|---|---|---|
| 저장소 | `nxtcloud-edu/2026-kmuct-kt-team01` | 원격 확인 완료 |
| 제출 기준 브랜치 | `main` | 원격 기본 브랜치 확인 완료 |
| 실행 ID | `20260920` | 기존 팀 브랜치 `work/20260920/role-3`과 일치 |
| AWS 리전 | `us-east-1` | 고정 |
| 역할 1 IAM | `kmu-proj-06` | 사전 안내 기준 후보. EC2 콘솔 드롭다운 확인 전 미검증 |
| EC2 주소 | 미할당 | 생성 후 공유 |

IAM 사용자명은 비밀값이 아니지만 현재 값은 AWS 리소스 생성 전에 역할 1 담당자가 콘솔에서 다시 확인해야 한다. Access Key, 세션 시크릿, DB 비밀번호 등 비밀값은 저장소·이슈·PR에 기록하지 않는다.

## 역할과 계정

| 역할 | 담당 | 책임 |
|---|---|---|
| 1 | `junseok0929` | 인프라, bootstrap, 배포, 최종 검토 |
| 2 | `seopseopi` | React 프론트엔드 |
| 3 | `y3rtcn` | 백엔드, 공유 모델·마이그레이션, 최종 통합 |
| 4 | `jooya38` | 사진 분석·품질 |
| 5 | `tkdgur3207` | 보정·승인 |

## 파일 소유권

| 소유자 | 경로 |
|---|---|
| 역할 1 | `infra/`, `scripts/`, `nginx.conf`, `systemd/` |
| 역할 2 | `frontend/package.json`, `frontend/src/App.tsx`, 라우팅, 공통 스타일 |
| 역할 3 | `backend/app/models.py`, `backend/alembic/`, `backend/requirements.txt` |
| 역할 4 | `backend/app/analysis.py`, `backend/app/quality.py` |
| 역할 5 | `backend/app/edits.py` |

소유하지 않은 파일 변경은 GitHub 이슈로 담당자에게 요청하며 병행 덮어쓰지 않는다.

## 현재 단계

- 공식 README 커밋이 이미 있으므로 `bootstrap/20260920` PR로 팀 설정을 추가한다.
- 역할 브랜치는 `work/20260920/role-N`, 통합 후보는 `assemble/20260920`이다.
- 원격에서 역할 3 브랜치가 확인됐다. 다른 역할의 실제 진행 상태는 확인하지 않았다.
- AWS 자원, IAM 인스턴스 프로파일, EC2 주소, 실제 Rekognition 호출은 아직 미검증이다.
- IAM 인스턴스 프로파일이 보이지 않으면 팀은 `FACE_PROVIDER=mock`으로 진행하고 QnA에 문의한다.
