# ZZIK 단일 EC2 배포 안내

이 문서는 AWS 연결 준비 절차다. 저장소 작성 시점에는 AWS 자원을 생성하거나 실호출하지 않았다. 실제 리소스 ID, 엔드포인트, 비밀번호, 세션 시크릿은 저장소에 기록하지 않는다.

## 현재 상태

| 항목 | 상태 |
|---|---|
| 리전 | `us-east-1`로 설계 완료, 실계정 미검증 |
| IAM 사용자 후보 | `kmu-proj-06`, 사용자 확인 필요 |
| 인스턴스 프로파일 | 콘솔 드롭다운 미확인 |
| S3 | 미생성 |
| RDS | 미생성 |
| EC2 및 퍼블릭 IP | 미생성 |
| Rekognition 권한 | EC2 인스턴스 역할에서 미검증 |
| 실제 배포/E2E | 미실행 |

## 1. 가장 먼저 확인할 것

EC2 시작 화면의 **고급 세부 정보 → IAM 인스턴스 프로파일**에서 `SafeInstanceProfile-kmu-proj-06` 또는 `SafeRole-kmu-proj-06`이 선택 가능한지 확인한다.

- 보임: 해당 프로파일을 EC2에 연결하고 다음 단계로 진행한다.
- 안 보임: 팀에 즉시 공유하고 주최측 QnA에 문의한다. 권한을 우회하거나 Access Key를 만들지 않는다. 해결 전에는 `FACE_PROVIDER=mock`으로 진행하고 화면/API에 mock임을 표시한다.

## 2. AWS 리소스 체크리스트

모든 리소스는 `us-east-1`에 만들며 다른 참가자의 리소스를 수정하지 않는다.

### S3

- 버킷명: `kmu-proj-06-zzik` — IAM 사용자명이 다르면 생성 전에 접두사를 수정한다.
- 퍼블릭 액세스 차단: 네 항목 모두 유지
- 기본 암호화: SSE-S3(AES-256)
- Versioning: 활성화. 사진 삭제 복구와 `scripts/backup-data.sh`에 필요
- 애플리케이션은 presigned URL로만 원본을 제공한다.

### RDS PostgreSQL

- Free Tier 템플릿을 사용한다.
- 퍼블릭 액세스 여부는 대회 당일 주최측 정책을 확인한 뒤 결정한다.
- DB 보안그룹 인바운드 5432의 소스는 EC2 보안그룹만 허용한다. `0.0.0.0/0`을 허용하지 않는다.
- 데모 DB와 별도로 이름이 `_test` 또는 `_e2e`로 끝나는 테스트 DB를 만든다.

### EC2

- AMI: 이름이 `nxtcloud-ami-v`로 시작하는 승인 AMI
- 타입: `t3.small` 권장(최대 2GB RAM)
- IAM 인스턴스 프로파일: 첫 단계에서 확인한 프로파일
- 애플리케이션 보안그룹: TCP 80만 `0.0.0.0/0`에 공개
- SSH는 주최측 정책이 허용한 관리 소스만 사용
- 8000은 외부에 열지 않는다.
- 퍼블릭 IP를 팀의 `[EC2_IP]`로 공유한다. 프론트 코드에는 주소를 넣지 않는다.

## 3. 호스트 준비

Amazon Linux 2023에서 Git, Nginx, PostgreSQL client, Python 3.13, Node 24를 승인된 패키지 경로로 설치한다. 시스템 `python3` 링크는 바꾸지 않는다. 아래 명령은 버전을 엄격히 확인한 뒤 전용 `zzik` 계정·가상환경·설정을 설치한다.

```bash
sudo ./scripts/install-host.sh
```

소스 저장소는 기본적으로 `/opt/zzik/source`에 두며 배포 스크립트의 `SOURCE_REPO`로 변경할 수 있다.

## 4. 런타임 환경변수

`infra/runtime.env.example`을 `/etc/zzik/runtime.env`로 복사하고 실제 값으로 바꾼다. 파일 소유자는 root, 권한은 600이어야 한다.

```bash
sudo install -o root -g root -m 600 infra/runtime.env.example /etc/zzik/runtime.env
sudo editor /etc/zzik/runtime.env
```

필수 값은 `DATABASE_URL`, `STORAGE_BACKEND=s3`, `S3_BUCKET`, `AWS_REGION=us-east-1`, `FACE_PROVIDER`, `WORKER_CONCURRENCY=1`, `SESSION_SECRET`이다. boto3에는 region만 전달하며 자격증명은 EC2 인스턴스 역할 표준 체인에 맡긴다.

## 5. 연결 전 검사

백엔드 가상환경에 역할 3의 잠긴 의존성을 설치한 뒤 실행한다.

```bash
set -a
source /etc/zzik/runtime.env
set +a
/opt/zzik/venv/bin/python scripts/preflight.py
```

출력은 DB `SELECT 1`, S3 `head_bucket`, Rekognition `list_collections`, STS `get_caller_identity` 네 검사의 JSON이다. 실패 출력에는 계정 ID, ARN, 버킷명, 키, SDK 원문 오류가 포함되지 않는다. readiness 성공만으로 이 네 검사가 성공했다고 판단하지 않는다.

## 6. 배포와 롤백

역할 3이 `backend/requirements.txt`, Alembic 설정, API와 worker 엔트리포인트를 제공한 후 실행한다.

```bash
sudo DEPLOY_BRANCH=main ./scripts/deploy.sh
```

배포는 fast-forward pull, Python 의존성 설치, Alembic upgrade, 프론트 빌드, release symlink 전환, API·worker 재시작 순서다. 이전 application release의 full SHA로 되돌릴 수 있다.

```bash
sudo ./scripts/rollback.sh <40-character-commit-sha>
```

롤백은 코드와 정적 파일만 되돌리고 DB를 자동 downgrade하지 않는다. 대상 코드가 현재 스키마와 호환되는지 먼저 확인한다.

## 7. 실제 주소 검증

1. `http://[EC2_IP]/api/health/ready`
2. `http://[EC2_IP]/`
3. 브라우저 Network에서 API 요청이 같은 origin의 `/api` 상대경로인지 확인
4. 전용 테스트 앨범에서 업로드 → S3 저장 → worker 처리 → 분석 완료 확인
5. Nginx, FastAPI, worker, RDS, S3, Rekognition 로그/상태를 계층별로 구분

HTTP만 사용한다. CORS middleware, HTTPS, ELB, CloudFront, NAT, private subnet은 이 배포에 추가하지 않는다.

## 8. 백업과 복구 검사

S3 Versioning이 활성화된 상태에서 다음 명령은 DB custom dump, SHA-256, S3 object-version manifest를 비공개 버킷의 `system-backups/<UTC timestamp>/`에 SSE-S3로 저장한다.

```bash
sudo --preserve-env=DATABASE_URL,S3_BUCKET,AWS_REGION ./scripts/backup-data.sh
```

복구는 이름이 `_test` 또는 `_e2e`로 끝나는 DB에서만 허용된다.

```bash
RESTORE_DATABASE_URL='postgresql://.../zzik_restore_test' \
  ./scripts/restore-db-test.sh system-backups/YYYYMMDDTHHMMSSZ
```

EC2 중지 전후에 RDS 행 수와 S3 object/version이 유지되는지 전용 테스트 데이터로 확인한다. 실제 데모 DB를 초기화하거나 복구 시험 대상으로 사용하지 않는다.

## 9. 대회 종료 후 정리

삭제 전 팀과 주최측 보존 정책을 확인한다. 필요한 DB final snapshot과 S3 백업/버전 manifest가 실제로 열리는지 확인한 뒤에만 다음 순서로 정리한다.

1. EC2 서비스 중지 및 인스턴스 종료
2. RDS final snapshot 생성·확인 후 인스턴스 삭제
3. S3 보존물이 필요 없다는 확인 후 object versions와 delete markers를 포함해 버킷 비우기
4. 버킷 삭제
5. 역할 1이 만든 보안그룹만 삭제

공유 IAM 역할, 주최측 AMI, 다른 참가자의 버킷·DB·보안그룹은 수정하거나 삭제하지 않는다.
