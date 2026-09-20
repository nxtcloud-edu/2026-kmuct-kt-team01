"""KIROTHON 팀(토큰사냥꾼) 데모용 mock manifest 등록.

시연을 위해 실제 팀 사진(본인 동의)을 backend/samples/mock_manifest.json 에 등록한다.
값(얼굴 수/등장 인물/태그/품질)은 사람이 사진을 직접 보고 적은 것이다 — AI가 사진을 본
결과를 사람이 확정했다는 뜻이지, 실시간 얼굴 인식 결과가 아니다. FACE_PROVIDER=mock 에서만
쓰인다.

실행: python -m scripts.seed_kirothon_manifest (repo root, venv 활성화 상태)
"""

from __future__ import annotations

from pathlib import Path

from backend.app.samples import add_sample

PHOTO_DIR = Path("/Users/seopseopi/kirothon/사진라벨링 copy")

SOURCE = "2026-09-20 KIROTHON 해커톤(토큰사냥꾼 팀) 현장에서 팀원이 직접 촬영"
LICENSE = "촬영자 및 사진에 등장한 팀원 전원 동의 (팀 자체 데모 시연용)"

# members 배열 순서: 0=유준석 1=이민섭 2=김규태 3=이상혁 4=황연주
JS, MS, GT, SH, YJ = 0, 1, 2, 3, 4

# (filename, face_count, member_slots, tags, quality(sharpness, brightness, eyes_open_ratio), label)
ENTRIES: list[tuple[str, int, list[int | None], list[str], tuple[float, float, float], str]] = [
    ("기타.jpeg", 0, [], [], (0, 0, 0), "책상 위 팀 명패 (얼굴 없음)"),
    ("기타1.jpeg", 0, [], [], (0, 0, 0), "AWS 사무실 입구"),
    ("기타2.jpeg", 4, [YJ, None, None, None], [], (55, 58, 1.0), "팀 버블슈터 게임 중"),
    ("기타3.jpeg", 0, [], [], (0, 0, 0), "AWS 사무실 입구 2"),
    ("기타4.jpeg", 0, [], [], (0, 0, 0), "방문자 배지 클로즈업"),
    ("기타5.jpeg", 6, [YJ, None, None, None, None, None], [], (60, 60, 0.83), "팀 전체 작업 테이블"),
    ("기타6.jpeg", 12, [None] * 12, [], (45, 55, 0.6), "해커톤 전체 강당"),
    ("음식.jpeg", 0, [], ["음식"], (0, 0, 0), "저녁 도시락"),
    ("김규태.jpeg", 1, [GT], [], (50, 55, 1.0), "김규태 - 식사 중 (카메라 안 봄)"),
    ("김규태,유준석.jpeg", 2, [GT, JS], [], (58, 58, 1.0), "김규태·유준석"),
    ("유준석.jpeg", 1, [JS], [], (72, 62, 1.0), "유준석 - 브이"),
    ("유준석,김규태.jpeg", 2, [JS, GT], [], (60, 57, 1.0), "유준석·김규태 (노트북 작업)"),
    ("이민섭.jpeg", 1, [MS], [], (65, 60, 1.0), "이민섭"),
    ("이상혁.jpeg", 1, [SH], [], (70, 62, 1.0), "이상혁"),
    ("이상혁,이민섭.jpeg", 2, [SH, MS], [], (78, 68, 1.0), "이상혁·이민섭 - 듀오 셀카"),
    ("이상혁2.jpeg", 1, [SH], [], (68, 58, 1.0), "이상혁 - 배지 클로즈업"),
    ("이상혁3.jpeg", 1, [SH], [], (74, 64, 1.0), "이상혁 - 엄지척"),
    ("황연주.jpeg", 1, [YJ], [], (76, 66, 1.0), "황연주 - 활짝 웃음"),
    ("황연주, 김규태.jpeg", 3, [YJ, None, GT], [], (56, 56, 1.0), "황연주·김규태 (+배경 인물)"),
    ("황연주,김규태.jpeg", 3, [YJ, None, GT], [], (58, 57, 1.0), "황연주·김규태 (+배경 인물) 2"),
    (
        "단체사진, 황연주, 유준석, 김규태, 이상혁.jpeg",
        4,
        [YJ, JS, GT, SH],
        [],
        (62, 60, 1.0),
        "4인 단체샷",
    ),
]


def main() -> None:
    for filename, face_count, member_slots, tags, quality, label in ENTRIES:
        path = PHOTO_DIR / filename
        image_bytes = path.read_bytes()
        sharpness, brightness, eyes_open_ratio = quality
        digest, entry = add_sample(
            image_bytes,
            source=SOURCE,
            license=LICENSE,
            face_count=face_count,
            label=label,
            tags=tags,
            quality={
                "sharpness": sharpness,
                "brightness": brightness,
                "eyes_open_ratio": eyes_open_ratio,
            }
            if face_count > 0
            else None,
            member_slots=member_slots if face_count > 0 else None,
            force=True,
        )
        print(f"{digest[:12]}  {label:40s}  faces={face_count}  slots={member_slots}")


if __name__ == "__main__":
    main()
