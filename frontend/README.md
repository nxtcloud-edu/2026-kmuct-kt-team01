# ZZIK frontend

React 19, TypeScript, Vite로 만든 찍(ZZIK) 프론트엔드다.

```bash
npm install
npm run dev
```

기본 실행은 `sample · mock` 배지가 표시되는 샘플 데이터 모드다. 실제 FastAPI와 연결할 때는
`?data=api`를 주소에 붙인다. 두 모드 모두 같은 `ApiClient` 계약을 사용하며 실제 API 요청은
서버 주소를 하드코딩하지 않고 같은 origin의 `/api`로만 전송한다. 세션 쿠키를 위해 모든 API
요청에 `credentials: 'include'`가 설정되어 있다.

검증 명령:

```bash
npm run typecheck
npm test
npm run build
npm audit --audit-level=moderate
```

5번 역할의 편집·승인 UI는 `src/components/EditorSlot.tsx`의 `EditorPanelProps`를 구현해 교체한다.
