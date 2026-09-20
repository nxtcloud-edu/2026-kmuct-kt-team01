# 역할 1 인계 기록

## 현재 단계

역할 1의 저장소 bootstrap, 단일 EC2용 Nginx/systemd 설정, 호스트 설치, 배포·롤백, AWS 사전점검, 백업·테스트 복구 코드 작성을 완료했다. 사용자 요청에 따라 AWS 자원은 생성·연결하지 않았으며 실제 사이트 배포도 아직 수행하지 않았다.

- 저장소: `nxtcloud-edu/2026-kmuct-kt-team01`
- 기준 브랜치: `main`
- 실행 ID: `20260920`
- 역할 브랜치: `work/20260920/role-1`
- 기록 시점 head: `e5acbeb82c5ad9a932ee5b5275996a9022e584ca`
- bootstrap head: `0af8c5df6a61667cf19144a4ea18a8e04d7d4604`

## 구현 상태

| 역할 1 산출물 | 상태 | 근거 |
|---|---|---|
| 팀 bootstrap·소유권·Git 규칙 | 완료 | `README.md`, `.gitignore`, `docs/TEAM_SETUP.md`, `docs/GIT_WORKFLOW.md` |
| DB/S3/Rekognition/STS preflight | 구현 완료, 실 AWS 미검증 | `scripts/preflight.py`, `scripts/test_preflight.py` |
| 같은 origin Nginx | 구현 완료, EC2 `nginx -t` 미실행 | `nginx.conf` |
| API·worker systemd | 구현 완료, EC2 기동 미검증 | `systemd/zzik-api.service`, `systemd/zzik-worker.service` |
| AL2023 호스트 bootstrap | 구현 완료, EC2 미실행 | `scripts/install-host.sh` |
| 커밋별 배포·application rollback | 구현 완료, 통합 배포 미실행 | `scripts/deploy.sh`, `scripts/rollback.sh` |
| DB/S3 백업·테스트 DB 복구 | 구현 완료, 실 저장소 미검증 | `scripts/backup-data.sh`, `scripts/restore-db-test.sh` |
| AWS 연결·보안·정리 절차 | 문서 완료, 자원 미생성 | `infra/README.md`, `infra/runtime.env.example` |

## 기능별 커밋

- `951ad45` — sanitized AWS preflight
- `3f86f2e` — same-origin Nginx
- `6dbced5` — API/worker systemd
- `b631957` — deploy/rollback
- `4f9c4a4` — AL2023 host bootstrap
- `bf8da01` — backup/test restore
- `897ccb9` — deferred AWS runbook
- `3ef0d17` — role 3 package layout와 deploy/systemd 정렬
- `e5acbeb` — 최신 `main`(역할 3 병합) 반영 및 `.gitignore` 양쪽 규칙 보존

## PR 상태

로컬 환경에 `gh` CLI가 없어 Draft PR과 GitHub 리뷰를 생성하지 못했다. 브랜치는 원격에 push했다.

- bootstrap 비교: <https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/compare/main...bootstrap/20260920?expand=1>
- 역할 1 비교: <https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/compare/main...work/20260920/role-1?expand=1>

## 실행한 검사

- 모든 shell script에 Git for Windows Bash `bash -n`: 통과
- `restore-db-test.sh`에 운영형 DB명 `zzik` 전달: `_test`/`_e2e` 보호 규칙으로 거부 확인
- 각 커밋 전 `git diff --cached --check`: 통과
- 비밀값 검사: AWS Access Key 패턴, `AWS_SECRET_ACCESS_KEY`, `aws configure` 지시 없음
- 원격 branch head: 각 기능 커밋 후 push하여 확인

## 실행하지 못한 검사

- 로컬에 Python과 `py` launcher가 없어 `scripts/test_preflight.py` 미실행
- 로컬에 Node 24, Nginx, systemd가 없어 프론트 빌드·`nginx -t`·`systemd-analyze verify` 미실행
- 사용자 요청에 따라 STS/S3/Rekognition/RDS 호출, EC2 배포, 실제 주소 E2E 미실행
- 운영·데모 데이터 대상 파괴 검사는 수행하지 않음

## 역할 3 검토 기록

역할 3 head `aac5017902061c667266a37223457eb1b2bb4bb2`를 확인했으나 이미 PR #1로 `main`에 병합된 뒤여서 GitHub 승인·수정요청을 남기지 못했다. 역할 1 경로 충돌은 `3ef0d17`에서 해결했다. 다음 사항은 역할 3 소유 파일의 후속 검토가 필요하다.

- production 설정 누락 시 SQLite/local storage/기본 session secret으로 폴백하지 않고 fail-closed 처리
- worker가 `processing`에서 종료됐을 때 stale job 재처리
- status/source 값과 tenant 간 관계의 DB 제약 강화
- PostgreSQL 전용 migration·cascade·`SKIP LOCKED` 검사

HTTP와 `Secure=false`, `SameSite=Lax`, `HttpOnly=true`는 HTTPS 사용이 금지된 이번 대회 제약에 따른 확정 결정이므로 역할 1에서 바꾸지 않았다.

## 남은 외부 조건

1. 사용자가 실제 IAM 사용자명을 확인하고 EC2 인스턴스 프로파일 드롭다운을 확인
2. 사용자 또는 주최측이 S3·RDS·EC2·보안그룹 생성
3. `/etc/zzik/runtime.env`에 실제 비밀값을 저장하고 권한 600 설정
4. 역할 2 프론트 및 역할 4/5 구현이 통합된 뒤 `scripts/deploy.sh` 실행
5. EC2에서 preflight, Nginx, API, worker, 업로드→분석 E2E, 백업→`_test` 복구 검사
6. 전체 기능 상태와 mock/실제 AI 범위는 최종 통합 후 README에 갱신

## 미처리 요청

- `ZZIK:20260920:role-1:R3-001` — from role 1, to role 3, kind `review`, 상태 `REQUESTED 초안(미게시)`. 위 역할 3 후속 검토 네 항목이 수락 기준이며 `gh` 부재로 GitHub 이슈를 생성하지 못했다.
