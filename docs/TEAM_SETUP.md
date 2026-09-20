# ZZIK 팀 설정

## 실행 값

| 항목 | 값 | 상태 |
|---|---|---|
| 저장소 | `nxtcloud-edu/2026-kmuct-kt-team01` | 원격 확인 완료 |
| 제출 기준 브랜치 | `main` | 원격 기본 브랜치 확인 완료 |
| 실행 ID | `20260920` | 팀 역할 브랜치와 일치 |
| AWS 리전 | `us-east-1` | 리소스 확인 완료 |
| 역할 1 IAM | `kmuct-ht-01` | `SafeInstanceProfile-kmuct-ht-01` 연결 확인 |
| EC2 | `i-04853d5e7a6793b35` / `34.231.109.51` | 실행 중, Session Manager 사용 |
| S3 | `kmuct-ht-01-zzik-photos` | 식별자 확인, 권한 preflight 대기 |
| RDS | `zzik-db.cj24wem202yj.us-east-1.rds.amazonaws.com:5432/zzik` | available, DB 연결 preflight 대기 |

리소스 식별자는 비밀값이 아니지만 Access Key, 세션 시크릿, DB 비밀번호 등 비밀값은 저장소·이슈·PR에 기록하지 않는다. EC2는 키 페어 없이 생성되어 SSH 대신 AWS Session Manager를 사용한다.

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
| 역할 3 | `backend/app/models.py`, Alembic, Python requirements |
| 역할 4 | `backend/app/analysis.py`, `backend/app/quality.py` |
| 역할 5 | `backend/app/edits.py` |

소유하지 않은 파일 변경은 GitHub 이슈로 담당자에게 요청하며 병행 덮어쓰지 않는다.

## 현재 단계

- 역할 1 Draft PR: `#12`, 브랜치 `work/20260920/role-1`
- 역할 3 백엔드는 `main`에 병합됐다.
- EC2·RDS·S3와 인스턴스 프로파일 식별자는 확보했다.
- 실제 DB/S3/Rekognition/STS preflight와 서비스 기동은 Session Manager에서 실행 대기 중이다.
- 포트 8000은 직접 API 확인을 위한 임시 진단 포트다. 가능하면 테스트 클라이언트 `/32`로 제한하고 통합 후 닫는다. 정상 사용자 트래픽은 Nginx의 80 포트를 사용한다.
