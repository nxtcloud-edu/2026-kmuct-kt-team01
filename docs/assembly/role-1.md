# 역할 1 인계 기록

## 한 줄 상태

역할 1 인프라 코드는 구현되어 Draft PR #12에 올라가 있고 EC2·RDS·S3도 생성됐지만, **EC2가 Systems Manager에 연결되지 않고 SSH 키도 없어 내부 설정과 실제 preflight를 실행할 접속 경로가 없는 상태**다.

## Git과 PR

- 저장소: `nxtcloud-edu/2026-kmuct-kt-team01`
- 기준 브랜치: `main`
- 실행 ID: `20260920`
- 역할 브랜치: `work/20260920/role-1`
- 인계 직전 head: `2727d7116b86e9f4489422b3de498cfb247d0ff6`
- Draft PR: <https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/pull/12>
- PR reviewer: `y3rtcn`
- 작업 트리와 원격 branch는 인계 직전에 동기화 확인

## 생성된 AWS 리소스

| 항목 | 값 | 확인 상태 |
|---|---|---|
| 리전/AZ | `us-east-1` / `us-east-1f` | 사용자 확인 |
| EC2 | `i-04853d5e7a6793b35` | 실행 중 |
| Public IPv4 | `34.231.109.51` | 사용자 확인 |
| Public DNS | `ec2-34-231-109-51.compute-1.amazonaws.com` | 사용자 확인 |
| AMI | `ami-0190258a3c1abc699` | 사용자 확인 |
| 인스턴스 프로파일 | `SafeInstanceProfile-kmuct-ht-01` | 사용자 화면 기준 연결, 정책 내용 미확인 |
| S3 | `kmuct-ht-01-zzik-photos` | 생성됨, 실제 `head_bucket` 미검증 |
| RDS endpoint | `zzik-db.cj24wem202yj.us-east-1.rds.amazonaws.com:5432` | `available` |
| RDS DB/user | `zzik` / `zzik` | 비밀번호는 저장소·채팅에 없음 |
| EC2 보안그룹 | `zzik-web-sg` | 80과 8000 인바운드 개방 |

Access Key는 만들거나 사용하지 않는다. boto3는 EC2 인스턴스 역할 표준 자격증명 체인을 사용해야 한다.

## 현재 차단 원인

1. EC2는 키 페어 없이 생성되어 SSH 접속이 불가능하다.
2. Session Manager 화면에서 `i-04853d5e7a6793b35 is not connected`가 표시된다.
3. 현재 AWS 콘솔 사용자에게 다음 조회 권한 거부도 표시됐다.
   - `ssm:DescribeInstanceInformation`
   - `ssm:GetConnectionStatus`
   - `ssm:GetServiceSetting`
   - `iam:GetInstanceProfile`
4. 외부에서 80/8000 TCP 연결을 시도했으나 응답하지 않았다. 보안그룹과 별개로 EC2 내부 서비스는 아직 listening하지 않는 것으로 판단한다.

정확한 SSM 미연결 원인은 EC2 내부 또는 IAM 정책을 볼 수 없어 확정하지 못했다. 관리자가 다음을 확인해야 한다.

- `SafeInstanceProfile-kmuct-ht-01`에 `AmazonSSMManagedInstanceCore` 상당 권한 존재
- AMI에 SSM Agent 설치 및 실행
- EC2에서 SSM endpoint로 HTTPS 443 outbound 가능
- 확인 후 EC2 재부팅 및 Session Manager 재접속

SSM 복구가 불가능하면 키 페어를 지정한 새 EC2가 필요하다. 기존 RDS와 S3는 재사용할 수 있다. 22 포트는 관리 소스 `/32`로만 제한한다.

## 역할 1 구현 상태

| 산출물 | 상태 | 파일 |
|---|---|---|
| 팀 bootstrap·소유권·Git 규칙 | 완료 | `README.md`, `.gitignore`, `docs/TEAM_SETUP.md`, `docs/GIT_WORKFLOW.md` |
| DB/S3/Rekognition/STS preflight | 구현 완료, EC2 미실행 | `scripts/preflight.py`, `scripts/test_preflight.py` |
| 실제 AWS runtime 생성 | 구현 완료, EC2 미실행 | `scripts/configure-runtime.sh`, `infra/runtime.env.example` |
| 같은 origin Nginx | 구현 완료, EC2 미실행 | `nginx.conf` |
| API·worker systemd | 구현 완료, EC2 미실행 | `systemd/zzik-api.service`, `systemd/zzik-worker.service` |
| AL2023 host bootstrap | 구현 완료, EC2 미실행 | `scripts/install-host.sh` |
| 커밋별 배포·application rollback | 구현 완료, 통합 미실행 | `scripts/deploy.sh`, `scripts/rollback.sh` |
| DB/S3 backup·test restore | 구현 완료, AWS 미실행 | `scripts/backup-data.sh`, `scripts/restore-db-test.sh` |
| AWS 운영 runbook | 실제 식별자 반영 완료 | `infra/README.md` |

## 최근 추가 커밋

- `bd594cd` — SQLAlchemy `postgresql+psycopg://` URL을 preflight에서 psycopg용 `postgresql://`로 정규화
- `2727d71` — 실제 EC2/RDS/S3 식별자와 안전한 runtime 생성 및 Session Manager 절차 반영

이전 기능별 커밋은 PR #12의 commit 목록에서 확인한다.

## 접속 복구 후 실행 순서

### 1. EC2 도구 확인

Session Manager 터미널에서 실행한다. 비밀값은 출력하지 않는다.

```bash
grep -E '^(NAME|VERSION_ID)=' /etc/os-release
git --version 2>&1 || echo 'git=MISSING'
python3.13 --version 2>&1 || echo 'python3.13=MISSING'
node --version 2>&1 || echo 'node=MISSING'
npm --version 2>&1 || echo 'npm=MISSING'
nginx -v 2>&1 || echo 'nginx=MISSING'
aws --version 2>&1 || echo 'aws=MISSING'
sudo ss -lntp | grep -E ':(80|8000)\b' || echo '80/8000=NOT_LISTENING'
```

Python 3.13과 Node 24를 사용해야 하며 시스템 `python3` 링크를 바꾸지 않는다.

### 2. 역할 1 브랜치 받기

```bash
sudo mkdir -p /opt/zzik
sudo chown "$USER":"$USER" /opt/zzik
git clone https://github.com/nxtcloud-edu/2026-kmuct-kt-team01.git /opt/zzik/source
git -C /opt/zzik/source switch work/20260920/role-1
```

이미 clone이 있으면 중복 clone 대신 다음을 사용한다.

```bash
git -C /opt/zzik/source fetch origin
git -C /opt/zzik/source pull --ff-only
```

### 3. runtime.env 생성

```bash
cd /opt/zzik/source
sudo ./scripts/configure-runtime.sh
sudo stat -c '%U:%G %a %n' /etc/zzik/runtime.env
```

스크립트가 RDS 비밀번호를 숨김 입력으로 받고 자동 URL-encoding한다. 비밀번호를 명령 인자, 채팅, Git에 넣지 않는다. 기대 권한은 `root:root 600`이다.

### 4. preflight

```bash
sudo python3.13 -m venv /opt/zzik/venv
sudo /opt/zzik/venv/bin/python -m pip install -r /opt/zzik/source/requirements.txt
sudo bash -c 'set -a; source /etc/zzik/runtime.env; set +a; cd /opt/zzik/source; /opt/zzik/venv/bin/python scripts/preflight.py'
```

다음 네 check가 모두 `ok: true`여야 한다.

- database: `SELECT 1`
- s3: `head_bucket`
- rekognition: `list_collections`
- sts: `get_caller_identity`

실패 시 출력은 고정 코드만 사용하므로 SDK 원문 오류를 팀 채널에 복사하지 않는다.

### 5. 사이트 배포

역할 1 브랜치에는 아직 프론트가 없으므로 현재 `deploy.sh` 전체 실행은 `frontend/package-lock.json` 검사에서 의도적으로 중단된다. 역할 3 통합 후보에 역할 2 프론트가 포함된 뒤 실행한다.

```bash
cd /opt/zzik/source
sudo ./scripts/install-host.sh
sudo DEPLOY_BRANCH=main ./scripts/deploy.sh
```

검증 주소:

- `http://34.231.109.51/`
- `http://34.231.109.51/api/health/ready`
- 임시 진단: `http://34.231.109.51:8000/api/health/ready`

8000은 사용자가 직접 API 확인을 위해 임시 개방했다. 가능하면 테스트 클라이언트 `/32`로 제한하고, 정상 Nginx 경로가 확인되면 닫는다.

## 실행한 검사

- 모든 shell script `bash -n`: 통과
- `restore-db-test.sh` 운영 DB명 차단: 통과
- 각 커밋 `git diff --cached --check`: 통과
- Access Key/실제 DB 비밀번호/실제 session secret 커밋 없음
- 역할 1 branch 로컬/원격 SHA 동기화 확인
- 외부 80/8000 연결: 응답 없음

## 실행하지 못한 검사

- 로컬 Python 부재로 `scripts/test_preflight.py` 미실행
- EC2 접속 불가로 OS·Python·Node·Nginx·AWS CLI 버전 미확인
- `/etc/zzik/runtime.env` 미생성
- RDS/S3/Rekognition/STS preflight 미실행
- Nginx/API/worker 기동 및 실제 URL smoke test 미실행
- 업로드→S3→worker→Rekognition E2E 미실행
- backup→`_test` DB restore 미실행

## 역할 3 검토 메모

역할 3 head는 역할 1 검토 전에 PR #1로 `main`에 병합됐다. 역할 1의 package/import 경로 충돌은 `3ef0d17`에서 해결했다. 역할 3 담당자가 후속 확인할 항목:

- production 설정 누락 시 SQLite/local storage/default secret으로 폴백하지 않고 fail-closed
- worker가 `processing` 중 종료됐을 때 stale job 재처리
- status/source와 tenant 관계의 DB 제약
- PostgreSQL migration·cascade·`SKIP LOCKED` 실제 검사

## 미처리 요청

- SSM 복구 요청 — 담당: AWS 관리자/QnA, 상태: `REQUESTED 필요`
- `ZZIK:20260920:role-1:R3-001` — 역할 3 후속 검토, 상태: `REQUESTED 초안(미게시)`
- PR #12는 Draft 상태를 유지하고 EC2 preflight 결과를 받은 뒤 검증 내역을 갱신한다.
