# ZZIK frontend

React 19, TypeScript, Vite로 만든 찍(ZZIK) 프론트엔드다.

```bash
npm install
npm run dev
```

기본 실행은 실제 FastAPI와 연결되는 API 모드다. 샘플 데이터를 둘러볼 때만
`?data=mock`을 주소에 붙인다. 두 모드 모두 같은 `ApiClient` 계약을 사용하며 실제 API 요청은
서버 주소를 하드코딩하지 않고 같은 origin의 `/api`로만 전송한다. 세션 쿠키를 위해 모든 API
요청에 `credentials: 'include'`가 설정되어 있다.

검증 명령:

```bash
npm run typecheck
npm test
npm run build
npm audit --audit-level=moderate
```

편집·승인 UI는 `src/editor/EditorPanel.tsx`에 구현되어 `src/pages/PhotoDetail.tsx`에서 사진 상세 화면과 연결된다.
