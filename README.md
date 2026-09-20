# 찍 / ZZIK

2026년 국민대학교 캠퍼스타운 키로톤 01팀 토큰사냥꾼 레포지토리입니다.

여행 공유 앨범에서 사진 업로드, 인물·장면·품질 분석, 분류·선택, 보정, 등장 멤버 전원 승인, 최종본 다운로드까지 연결하는 서비스입니다.

## 해커톤 실행 정보

- 공식 저장소: `nxtcloud-edu/2026-kmuct-kt-team01`
- 제출 기준 브랜치: `main`
- 실행 ID: `20260920`
- 서비스 리전: `us-east-1`
- 배포 구조: EC2 1대(Nginx + FastAPI + worker), 외부 RDS PostgreSQL, 비공개 S3
- 인증 범위: 초대코드 + 이름, 서명된 세션 쿠키

팀 구성, 파일 소유권, 브랜치 규칙은 [`docs/TEAM_SETUP.md`](docs/TEAM_SETUP.md)와 [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md)를 따릅니다.

## 현재 상태

이 브랜치는 대회용 신규 구현의 bootstrap 단계입니다. 기능 완료 여부와 실제 AWS/AI 검증 결과는 구현 PR과 역할별 `docs/assembly/role-N.md`에서 구분해 기록합니다. fixture/mock 결과를 실제 Rekognition 성공으로 표시하지 않습니다.
