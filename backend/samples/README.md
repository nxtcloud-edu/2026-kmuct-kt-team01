# mock 샘플과 출처 기록 (역할 4)

`FACE_PROVIDER=mock` 은 AWS를 전혀 호출하지 않는다. 결과는 파일 sha256을 시드로 한 결정론적 값이다.

## 두 가지 경로

| mock_source | 언제 | 의미 |
|---|---|---|
| `manifest` | 파일 sha256이 `mock_manifest.json`의 `samples`에 있을 때 | 사람이 직접 적어 넣은 정답 |
| `synthetic` | 등록되지 않은 파일 | 해시로 만든 **가짜값**. 얼굴마다 `synthetic: true`, 응답 `warnings`에 경고가 붙는다 |

두 경우 모두 `mode="mock"` 이다. 프론트는 `mode === "mock"` 이면 "샘플 분석" 배지를 띄운다.
mock의 인물 매칭은 실제 얼굴 인식 결과가 아니다. 정확도로 발표하지 않는다.

`MOCK_SYNTHETIC_MATCH=0` 으로 두면 등록되지 않은 사진에는 아무 인물도 붙이지 않는다
(모든 얼굴 `member_id=null`). 데모/심사 화면에서 합성 매칭을 아예 끄고 싶을 때 쓴다.

## 샘플 등록 방법

```bash
python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" photo.jpg
```

나온 해시를 키로 `mock_manifest.json`의 `samples`에 넣는다. `source`와 `license`는 반드시 적는다.

## 현재 등록된 이미지의 출처

**없음.** 2026-09-20 기준 `samples` 는 비어 있다.
저장소에 사람 얼굴 사진을 커밋하지 않았다. 테스트는 Pillow로 그 자리에서 만드는 합성 이미지
(단색·도형)만 쓰므로 초상권·라이선스 문제가 없다. 실사진을 등록할 때 이 표를 채운다.

| 파일 | sha256 | 출처 | 사용 허락 |
|---|---|---|---|
| (없음) | | | |
