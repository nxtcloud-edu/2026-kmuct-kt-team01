# ZZIK 단일 EC2 배포 안내

실제 AWS 리소스 식별자는 확보됐으며 비밀값은 저장소에 기록하지 않는다. EC2는 키 페어 없이 생성되어 AWS 콘솔의 Session Manager로 관리한다.

## 현재 리소스

| 항목 | 값 | 상태 |
|---|---|---|
| 리전 | `us-east-1` (`us-east-1f`) | 확인 완료 |
| EC2 | `i-04853d5e7a6793b35`, `34.231.109.51` | Session Manager 접속 사용 |
| 인스턴스 프로파일 | `SafeInstanceProfile-kmuct-ht-01` | 연결 확인 |
| S3 | `kmuct-ht-01-zzik-photos` | 실제 권한 preflight 대기 |
| RDS | `zzik-db.cj24wem202yj.us-east-1.rds.amazonaws.com:5432/zzik`, user `zzik` | available, 연결 preflight 대기 |
| Rekognition | `us-east-1` | 인스턴스 역할 권한 preflight 대기 |
| 배포/E2E | `http://34.231.109.51` | 서비스 기동 대기 |

## 보안그룹

- 정상 사용자 트래픽: TCP 80
- RDS 5432: EC2 보안그룹에서만 허용하며 `0.0.0.0/0` 금지
- TCP 8000: 사용자가 직접 API 확인을 위해 임시 개방했다. 가능하면 테스트 클라이언트의 `/32`로 제한하고 통합 완료 후 닫는다.
- SSH 키가 없으므로 22 포트를 추가로 열지 않는다.
- Nginx는 `/api`를 `127.0.0.1:8000`으로 전달하며 최종 서비스는 80 포트를 사용한다.

## Session Manager 연결 순서

1. AWS 콘솔 → EC2 → `i-04853d5e7a6793b35` 선택
2. **연결 → Session Manager → 연결**
3. 아래 환경 확인 명령 실행

```bash
cat /etc/os-release
git --version
python3.13 --version
node --version
nginx -v
aws --version
```

Python은 3.13, Node는 24여야 한다. AL2023 시스템 `python3` 링크를 바꾸지 않는다.

## 소스 준비

Session Manager에서 저장소를 준비한다. 역할 1 PR 병합 전에는 역할 1 브랜치를 사용하고, 병합 후에는 `main`을 사용한다.

```bash
sudo mkdir -p /opt/zzik
sudo chown "$USER":"$USER" /opt/zzik
git clone https://github.com/nxtcloud-edu/2026-kmuct-kt-team01.git /opt/zzik/source
git -C /opt/zzik/source switch work/20260920/role-1
```

기존 clone이 있으면 새로 만들지 말고 다음만 실행한다.

```bash
git -C /opt/zzik/source fetch origin
git -C /opt/zzik/source pull --ff-only
```

## runtime.env 생성

비밀번호를 명령줄 인자나 shell history에 넣지 않는다. 다음 스크립트가 RDS 비밀번호를 숨김 입력으로 받고 URL-encoding하며, `SESSION_SECRET`을 새로 생성해 권한 600으로 저장한다.

```bash
cd /opt/zzik/source
sudo ./scripts/configure-runtime.sh
sudo stat -c '%U:%G %a %n' /etc/zzik/runtime.env
```

기대 권한은 `root:root 600`이다. boto3 자격증명은 `SafeInstanceProfile-kmuct-ht-01` 표준 체인을 사용하며 Access Key를 파일에 쓰지 않는다.

## 연결 전 preflight

역할 3의 고정 의존성을 Python 3.13 가상환경에 설치한 뒤 검사한다.

```bash
sudo python3.13 -m venv /opt/zzik/venv
sudo /opt/zzik/venv/bin/python -m pip install -r /opt/zzik/source/requirements.txt
sudo bash -c 'set -a; source /etc/zzik/runtime.env; set +a; cd /opt/zzik/source; /opt/zzik/venv/bin/python scripts/preflight.py'
```

DB `SELECT 1`, S3 `head_bucket`, Rekognition `list_collections`, STS `get_caller_identity` 네 결과가 모두 `ok: true`여야 한다. 출력에는 계정 ID, ARN, 버킷명, 키, SDK 원문 오류가 포함되지 않는다.

## 호스트 설정 및 배포

프론트가 통합되어 `frontend/package-lock.json`이 존재할 때 실행한다.

```bash
cd /opt/zzik/source
sudo ./scripts/install-host.sh
sudo DEPLOY_BRANCH=main ./scripts/deploy.sh
```

역할 1 PR이 아직 병합되지 않았다면 배포 브랜치를 임시로 지정한다.

```bash
sudo DEPLOY_BRANCH=work/20260920/role-1 ./scripts/deploy.sh
```

단, 역할 1 브랜치에는 프론트 통합 전까지 `frontend/`가 없으므로 전체 사이트 배포는 실패하도록 설계돼 있다. 역할 3 통합 후보에 프론트가 포함된 후 실행한다.

## 실제 주소 검증

1. `http://34.231.109.51/api/health/ready`
2. `http://34.231.109.51/`
3. 임시 직접 확인: `http://34.231.109.51:8000/api/health/ready`
4. 브라우저 Network에서 `/api` 상대경로 확인
5. 전용 테스트 앨범에서 업로드 → S3 → worker → Rekognition 완료 확인

readiness는 Nginx/API 기동만 보여주며 S3·RDS·Rekognition 권한은 preflight와 실제 작업으로 따로 확인한다.

## 백업과 테스트 복구

S3 Versioning 활성화 후 실행한다.

```bash
sudo bash -c 'set -a; source /etc/zzik/runtime.env; set +a; cd /opt/zzik/source; ./scripts/backup-data.sh'
```

복구는 이름이 `_test` 또는 `_e2e`로 끝나는 DB에서만 허용된다.

```bash
RESTORE_DATABASE_URL='postgresql://.../zzik_restore_test' \
  S3_BUCKET='kmuct-ht-01-zzik-photos' \
  AWS_REGION='us-east-1' \
  ./scripts/restore-db-test.sh system-backups/YYYYMMDDTHHMMSSZ
```

## 롤백과 정리

```bash
sudo ./scripts/rollback.sh <40-character-commit-sha>
```

롤백은 코드와 정적 파일만 되돌리고 DB를 자동 downgrade하지 않는다. 대회 종료 후에는 필요한 RDS snapshot과 S3 보존물을 확인한 다음 역할 1이 만든 EC2/RDS/S3/보안그룹만 정리한다. 공유 IAM 역할, 주최측 AMI, 다른 참가자의 리소스는 수정하거나 삭제하지 않는다.
