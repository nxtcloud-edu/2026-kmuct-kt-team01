# 찍 / ZZIK

**여행 사진을 함께 모으고, 나오는 사람 모두가 승인한 보정본을 고르는 공유 앨범 서비스입니다.**

2026년 국민대학교 캠퍼스타운 키로톤 01팀 **토큰사냥꾼** 프로젝트입니다.

앨범 생성·참여 → 기준 얼굴 등록 → 사진 업로드 → 인물·품질 분석 → 사진 선택·보정 → 전원 승인 → 다운로드 흐름을 제공합니다.

## 주요 기능

| 기능 | 구현 내용 |
|---|---|
| 공유 앨범 | 초대코드와 이름으로 생성·참여, 서명된 세션 쿠키로 앨범 접근 제어 |
| 사진 업로드 | JPEG·PNG 다중 업로드, 파일별 성공·실패 반환, 원본 바이트와 SHA-256 보존 |
| 사진 분석 | 기준 얼굴과 인물 매칭, 장면 태그·품질 지표, 분석 상태 조회·재시도 |
| 얼굴 상태 구분 | 확정 인물, 미확정 얼굴, 미등록 얼굴, 사람 없는 사진을 구분 |
| 갤러리 | 내 사진·단체샷·인물 조합·태그 필터, 촬영 시각·추천 점수 정렬, 연사 대표 컷 |
| 보정 버전 | 원본 기반 밝기·채도 조절, 원본 비교, 이전 버전에서 새 버전 생성 |
| 공동 승인 | 등장 확정 멤버의 명시적 승인, 승인 취소, 최종본 자동 집계 |
| 다운로드 | 원본, 저장된 보정본 미리보기·개별 다운로드, 선택 사진 ZIP API |
| 누락 현황 | 앨범 전체 사진 수와 멤버별 등장 사진 수 확인 |

분석 worker는 API와 별도 프로세스로 실행됩니다. 중단된 분석은 5분 lease 이후 회수하며 최대 3회 작업 시도 후 실패 처리합니다.

## 보정과 승인 규칙

- 밝기는 `0.5~1.5`, 채도는 `0.0~2.0` 범위입니다. 전체 설정을 항상 **원본**에 적용하며 보정본을 덮어쓰지 않습니다.
- 새 버전은 승인 0개로 시작합니다. 좋아요나 저장 행위를 승인으로 취급하지 않습니다.
- 분석 완료 후 현재 앨범의 확정된 등장 멤버가 승인합니다. `no_face`이거나 확정 멤버가 없으면 업로더 1명의 승인이 필요합니다.
- 미확정·미등록 얼굴을 임의로 승인 대상에 넣지 않습니다.
- 승인 조건을 충족한 버전 중 번호가 가장 큰 버전이 최종본입니다. 승인 취소 시 이전 충족 버전으로 돌아갈 수 있습니다.
- 인물 변경이나 재분석 시 기존 승인을 무효화합니다.
- 조절 중 CSS 미리보기는 근사값입니다. 저장된 버전을 선택하면 서버가 만든 JPEG를 표시하며, 해당 보정본 다운로드도 같은 객체를 사용합니다.

## 기술 구성

| 영역 | 기술 |
|---|---|
| 프론트엔드 | React 19, TypeScript, Vite, Vitest |
| API | Python 3.13, FastAPI, 서명 세션 쿠키 |
| 데이터베이스 | SQLAlchemy 2, Alembic, PostgreSQL / 로컬 SQLite |
| 이미지 처리 | Pillow, 원본·썸네일·보정본 분리 저장 |
| 분석 | Amazon Rekognition 어댑터 / 명시적인 mock 제공자 |
| 저장소 | 로컬 파일 / 비공개 Amazon S3 |
| 배포 | Nginx + FastAPI + worker를 단일 EC2에서 실행, 외부 RDS·S3 연결 |

의존성 버전은 [requirements.txt](requirements.txt)와 [frontend/package-lock.json](frontend/package-lock.json)을 기준으로 설치합니다.

```text
브라우저
  └─ Nginx :80
       ├─ /      → 프론트엔드 정적 빌드
       └─ /api   → FastAPI 127.0.0.1:8000
                       ├─ PostgreSQL / RDS
                       └─ 비공개 S3
                  worker → DB 작업 조회 → 사진 분석 → 결과 저장
```

## 빠르게 화면 보기

Node.js 24와 npm이 필요합니다.

```bash
git clone https://github.com/nxtcloud-edu/2026-kmuct-kt-team01.git
cd 2026-kmuct-kt-team01
git switch main
cd frontend
npm ci
npm run dev
```

터미널에 표시된 Vite 주소로 접속합니다. 기본값은 **샘플 데이터 모드**이며 백엔드 없이 화면을 확인할 수 있습니다. 샘플 업로드·분석 결과는 실제 데이터 저장이나 얼굴 인식을 의미하지 않으며, 샘플 사진의 보정 저장·다운로드는 제한됩니다. 샘플 이미지는 외부 이미지 URL을 사용합니다.

## 로컬 백엔드 실행

저장소 루트에서 Python 3.13 가상환경을 만듭니다.

```bash
python -m venv .venv
```

Windows PowerShell은 `.\.venv\Scripts\Activate.ps1`, macOS/Linux는 `source .venv/bin/activate`로 활성화한 뒤 설치합니다.

```bash
python -m pip install -r requirements.txt
```

다음은 **PowerShell 기준** 로컬 SQLite·파일 저장소 설정입니다. API와 worker를 실행하는 각 터미널에서 동일하게 설정합니다.

```powershell
$env:DATABASE_URL = 'sqlite+pysqlite:///./zzik_local.db'
$env:STORAGE_BACKEND = 'local'
$env:LOCAL_STORAGE_PATH = './storage'
$env:FACE_PROVIDER = 'mock'
$env:AWS_REGION = 'us-east-1'
$env:SESSION_SECRET = 'replace-with-your-own-local-secret'
```

macOS/Linux에서는 같은 값을 `export NAME=value` 형식으로 설정합니다. API 설정은 `.env`도 읽지만 **Alembic과 분석 제공자 설정을 함께 적용하려면 프로세스 환경변수로 전달**해야 합니다. [.env.example](.env.example)은 PostgreSQL 연결 예시이므로 로컬 SQLite 실행 시 위 값을 사용합니다.

최초 실행 및 스키마 변경 후 마이그레이션을 적용하고 API를 시작합니다.

```bash
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

별도 터미널에서 같은 가상환경과 환경변수를 사용해 worker를 실행합니다.

```bash
python -m backend.app.worker
```

- API 문서: `http://127.0.0.1:8000/docs`
- DB 준비 상태: `http://127.0.0.1:8000/api/health/ready`
- worker를 실행하지 않으면 업로드된 사진의 분석이 대기 상태에 머무릅니다.
- readiness는 DB 연결 검사이며 S3·Rekognition·전체 사용자 흐름의 성공을 보장하지 않습니다.

### 프론트와 실제 API 연결

프론트 주소에 `?data=api`를 붙이면 실제 API 모드로 전환됩니다. 모든 요청은 같은 origin의 `/api`를 사용합니다.

개발 환경에서는 Vite가 `/api` 요청을 기본 `http://127.0.0.1:8000`으로 프록시합니다. API와 worker를 실행한 뒤 Vite 주소에 `?data=api`를 붙여 접속합니다. 백엔드 주소를 바꾸려면 `frontend/.env.local`에 `VITE_API_TARGET`을 설정하고 Vite를 다시 시작합니다.

배포 환경에서는 [nginx.conf](nginx.conf)처럼 정적 프론트와 `/api` 프록시를 같은 origin에서 제공하며, `http://<EC2_IP>/?data=api`로 접속합니다.

```bash
cd frontend
npm run build
```

빌드 결과는 `frontend/dist/`에 생성됩니다. 서버 설치·배포·롤백은 [인프라 안내](infra/README.md)와 [배포 스크립트](scripts/deploy.sh)를 참고하세요.

## 설정과 분석 모드

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | SQLAlchemy DB 연결 문자열. API·worker·Alembic에 동일하게 적용 |
| `SESSION_SECRET` | 세션 서명 키. 재시작 후에도 같은 세션을 유지하려면 동일 값 사용 |
| `STORAGE_BACKEND` | `local` 또는 `s3` |
| `LOCAL_STORAGE_PATH` | 로컬 저장소 경로. API와 worker가 동일 위치 사용 |
| `S3_BUCKET` | S3 모드에서 사용할 비공개 버킷 |
| `AWS_REGION` | `us-east-1` |
| `FACE_PROVIDER` | `mock` 기본값 / `rekognition` |
| `MOCK_MANIFEST_PATH` | mock 샘플 정의 파일. 기본 `backend/samples/mock_manifest.json` |

프론트 샘플 모드와 백엔드 mock 분석은 별개입니다. `?data=api`에서도 `FACE_PROVIDER=mock`이면 실제 저장·API 흐름에 **합성 분석 결과**를 사용합니다. mock 결과와 similarity 점수를 실사진 인식 정확도로 해석하지 않습니다.

Rekognition 모드는 AWS 권한이 필요하며 인증 실패를 mock 성공으로 바꾸지 않습니다. 배포 자격증명은 EC2 인스턴스 역할 등 표준 자격증명 체인을 사용합니다. 세부 입출력은 [사진 분석 계약](docs/contracts/role-4-analysis.md)을 참고하세요.

## 테스트

백엔드는 저장소 루트에서 실행합니다.

```bash
python -m pytest -q
python -m pytest docs/assembly/checks/role5_acceptance.py -q
```

두 번째 명령은 원본 보존, 두 세션 승인·취소, 최종 ZIP, 재시작, 분석 중 수동 수정에 대한 별도 수락 검사입니다. 검사에는 임시 `_test` DB와 테스트 저장소를 사용합니다.

프론트는 `frontend/`에서 실행합니다.

```bash
npm run typecheck
npm test
npm run build
```

검증 이력은 [최종 통합 기록](docs/assembly/final-integration.md), 후속 수락 검사 결과는 [ROLE-05 작업 기록](docs/assembly/role-5.md)을 참고하세요. 테스트 통과와 실제 AWS·PostgreSQL 동시성·EC2 배포 검증은 구분합니다.

## 현재 제한사항

- 이 README는 `main`의 `d60e4ae495c21c2287d512cce202acfb91dca9bf` 코드를 기준으로 작성했습니다.
- 파일당 업로드 한도는 25 MiB, 보정 픽셀 한도는 2천만 픽셀입니다. Nginx의 요청 전체 한도는 `30M`이므로 여러 파일을 한 번에 보낼 때 전체 요청 크기도 영향을 받습니다.
- 원본·보정본 다운로드의 `Content-Disposition`에 비 ASCII 파일명을 직접 넣는 코드가 남아 있어 한글 파일명 다운로드 오류 수정이 필요합니다. [관련 요청](https://github.com/nxtcloud-edu/2026-kmuct-kt-team01/issues/7).
- 최종 ZIP은 API에서 `version="final"`로 요청할 수 있습니다. 갤러리의 선택 ZIP UI는 기본 원본 다운로드를 사용합니다. 개별 보정본 다운로드는 최종 승인 전 저장 버전에도 제공됩니다.
- 미등록 인물 그룹·여행 요약 관련 모듈은 존재하지만 현재 메인 화면/API에 연결된 기능과는 구분해야 합니다.
- 실제 AWS 호출, 전용 PostgreSQL 동시성, EC2 배포 및 실제 환경 전체 흐름은 별도 검증 대상입니다.

## 저장소 구조

```text
backend/app/       API·모델·스토리지·분석·보정·worker
backend/tests/    ROLE-05 렌더·버전·승인 테스트
frontend/src/     앨범 화면·API 클라이언트·편집 패널
alembic/          DB 마이그레이션
tests/            공통 API·스토리지·분석·worker 테스트
docs/             팀 계약·역할별 인계·통합 및 수락 검사 기록
infra/            배포 환경 안내
scripts/          배포·사전 검사·백업·복구·롤백
systemd/          API·worker 서비스 설정
```

## 팀

| 담당 | 역할 |
|---|---|
| [junseok0929](https://github.com/junseok0929) | 인프라·배포 |
| [seopseopi](https://github.com/seopseopi) | 프론트엔드 |
| [y3rtcn](https://github.com/y3rtcn) | 백엔드·최종 통합 |
| [jooya38](https://github.com/jooya38) | 사진 분석·품질 |
| [tkdgur3207](https://github.com/tkdgur3207) | 이미지 보정·버전·승인 |

제출 기준 브랜치는 `main`, 실행 ID는 `20260920`입니다. 협업 규칙은 [팀 설정](docs/TEAM_SETUP.md)과 [Git 작업 규칙](docs/GIT_WORKFLOW.md)에 정리돼 있습니다.
