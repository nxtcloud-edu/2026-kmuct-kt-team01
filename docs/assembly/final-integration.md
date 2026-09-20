# ZZIK 최종 통합 기록

통합 브랜치: `assemble/20260920`

## 완료된 사용자 흐름

1. 초대 코드로 앨범을 만들거나 참여하고 서명 세션을 발급한다.
2. 기준 얼굴 사진과 여행 사진을 등록한다.
3. worker가 사진을 분석하고 인물, 미확정 얼굴, 미등록 얼굴, 사람 없는 사진을 구분한다.
4. 앨범에서 인물·태그·단체 사진·연사 대표 사진을 조회한다.
5. 원본 바이트를 보존한 채 보정 버전을 만들고 등장 인물의 승인을 모은다.
6. 서버가 렌더링한 보정본을 미리 보고 개별 또는 ZIP으로 내려받는다.

## 최종 결함 수정

- `f53d976`: JPEG/PNG 업로드 원본을 재인코딩하지 않고 그대로 보존한다. 원본 MIME, 크기, 해시와 저장 객체가 일치한다.
- `3d3510f`: 저장된 보정 버전의 서버 미리보기와 개별 다운로드를 인증된 API로 제공한다.
- `b672000`: `matched`, `uncertain`, `unregistered`, `no_face`와 분석 실패를 화면에서 구분한다.
- `a34699f`: 중단된 worker 작업을 lease 뒤 회수하고 재시도 한도를 적용한다.
- `e5b5768`: 분석 중 수동 인물 변경을 보존하고 no_face 승인과 최종 ZIP 정책을 일치시킨다.

## 검증

- Python 3.13: 역할 5 조립 수락 검사를 포함해 222 tests passed
- 프론트: TypeScript, 23 Vitest tests, production build passed
- Alembic: `0001`부터 `0003`까지 upgrade/check/downgrade/upgrade passed
- npm audit: 0 vulnerabilities
- Python compile, shell syntax, Git whitespace checks passed

실제 AWS, 전용 PostgreSQL, EC2 배포는 해당 자격증명과 인프라에서 별도로 실행한다. 기본 제공자 설정은 mock이므로 AWS 권한이 없는 환경에서도 샘플 분석임을 명시해 실행할 수 있다.
