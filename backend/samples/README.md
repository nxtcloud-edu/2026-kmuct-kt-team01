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

`backend/app/samples.py` 가 해시 계산·검증·기록을 대신한다. JSON을 손으로 고치지 않는다.

```bash
python -m backend.app.samples add photo.jpg --faces 2 --tags 바다 \
    --source "2026-09-20 팀 직접 촬영" --license "피사체 4인 구두 동의"

python -m backend.app.samples list
python -m backend.app.samples remove <sha256>
```

- `--source`(출처)와 `--license`(사용 허락)는 **비워 둘 수 없다.** 저작권·초상권이
  확인되지 않은 이미지를 등록하지 못하게 하려는 것이다.
- `--faces` 는 **사람이 직접 센 얼굴 수**다. 도구가 얼굴을 세지 않는다.
- `--tags` 는 위 9종만 받는다. "해운대" 같은 고유명사는 거부된다.
- 이미지 파일을 저장소에 복사하지 않는다. 해시만 기록한다.

선택 인자: `--label`(읽을 이름), `--member-slots`(얼굴 순서대로 members 인덱스, 매칭 없음은 생략),
`--reference-faces`(`validate_reference` 용 얼굴 수), `--force`(이미 등록된 이미지 덮어쓰기).

## 현재 등록된 이미지의 출처

2026-09-20 기준 `samples` 에 21건 등록되어 있다. `scripts/seed_kirothon_manifest.py` (팀
자체 데모용) 로 KIROTHON 해커톤 현장에서 팀원이 직접 촬영한 사진을 등록했다 — 출처·사용
허락은 각 manifest 항목에 동일하게 `source="2026-09-20 KIROTHON 해커톤(토큰사냥꾼 팀)
현장에서 팀원이 직접 촬영"`, `license="촬영자 및 사진에 등장한 팀원 전원 동의 (팀 자체
데모 시연용)"` 로 남아 있다.

저장소에는 사진 파일 자체를 커밋하지 않았다(해시·설명만). 테스트는 여전히 Pillow로 그
자리에서 만드는 합성 이미지(단색)만 쓴다.

출처 기록은 이 파일의 표가 아니라 **manifest 항목 자체**(`source`, `license` 필드)에 남는다.
`python -m backend.app.samples list` 로 언제든 확인할 수 있다. 등록 도구가 두 값을 필수로
받으므로, manifest 에 있는 모든 항목에는 출처와 사용 허락이 반드시 붙어 있다.
