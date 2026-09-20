"""연사(버스트) 데모용 '비슷한 사진 여러 장' 묶음 2세트를 만들어 업로드한다.

기존 KIROTHON 데모 앨범에 사람이 실제로 촬영한 것처럼 보이는 연속 컷 세트를 추가한다.
황연주·이상혁 프로필 사진을 원본으로 삼아 약간씩 다른(살짝 더 어둡게/흔들리게/밝게) 버전을
PIL로 만들고, EXIF 촬영시각을 3초 이내로 좁혀 넣어 worker.recompute_bursts() 가 실제로
같은 burst_group_id 로 묶고 그중 품질이 제일 좋은 컷을 is_best 로 고르게 한다 — 화면에
보여주기 위해 값을 억지로 넣는 게 아니라 진짜 버스트 로직을 통과시킨다.

실행: python -m scripts.seed_burst_demo --base-url http://127.0.0.1:8001 \
        --invite-code itXV_EiwdQI --member 황연주:...member_id... --member 이상혁:...
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

import httpx
from itsdangerous import URLSafeSerializer
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from backend.app.samples import add_sample

PHOTO_DIR = Path("/Users/seopseopi/kirothon/사진라벨링 copy")
SOURCE = "2026-09-20 KIROTHON 해커톤(토큰사냥꾼 팀) 현장에서 팀원이 직접 촬영 (연속 컷)"
LICENSE = "촬영자 및 사진에 등장한 팀원 전원 동의 (팀 자체 데모 시연용)"

JS, MS, GT, SH, YJ = 0, 1, 2, 3, 4


def _variant(base: Image.Image, *, brightness: float, blur: float, crop_pct: float) -> bytes:
    img = base
    if crop_pct:
        w, h = img.size
        dx, dy = int(w * crop_pct), int(h * crop_pct)
        img = img.crop((dx, dy, w - dx, h - dy))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def _with_exif_time(jpeg_bytes: bytes, timestamp: str) -> bytes:
    img = Image.open(io.BytesIO(jpeg_bytes))
    exif = Image.Exif()
    exif[306] = timestamp  # DateTime — storage.py falls back to this when 36867 is absent
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=88, optimize=True)
    return buf.getvalue()


# (변형 이름, 밝기 배수, 블러 반경, 크롭 비율) — 인덱스 0 이 가장 좋은 컷이 되도록 짠다.
VARIANTS = [
    ("또렷함(베스트)", 1.00, 0.0, 0.0),
    ("살짝 흔들림", 1.00, 1.6, 0.01),
    ("약간 어둡게", 0.82, 0.4, 0.02),
    ("살짝 과다노출", 1.18, 0.0, 0.015),
]

# (그룹 라벨, member_slots 인덱스, 원본 프로필 파일, 그룹 시작 시각(HH:MM:SS), quality 목록)
GROUPS = [
    (
        "황연주",
        YJ,
        "황연주(본인).jpeg",
        "16:00:0",  # + 0,1,2,3초
        [(78, 68, 1.0), (55, 65, 1.0), (50, 48, 1.0), (58, 82, 1.0)],
    ),
    (
        "이상혁",
        SH,
        "이상혁(본인).jpeg",
        "16:05:0",
        [(76, 66, 1.0), (54, 63, 1.0), (49, 47, 1.0), (57, 80, 1.0)],
    ),
]


def build_group_files(group_label: str, member_index: int, source_file: str, time_prefix: str, qualities):
    source = Image.open(PHOTO_DIR / source_file)
    # 원본은 물리적으로는 옆으로 찍혀 있고 EXIF Orientation 태그로 바로 세워 보여진다.
    # 아래서 새 EXIF(촬영시각)로 통째로 덮어쓰므로, 태그에 기대지 말고 지금 픽셀 자체를 바로 세운다.
    base = ImageOps.exif_transpose(source).convert("RGB")
    base.thumbnail((1600, 1600))
    entries = []
    for i, ((name, brightness, blur, crop_pct), quality) in enumerate(zip(VARIANTS, qualities)):
        raw = _variant(base, brightness=brightness, blur=blur, crop_pct=crop_pct)
        timestamped = _with_exif_time(raw, f"2026:09:20 {time_prefix}{i}")
        filename = f"{group_label}_연속컷_{i + 1}.jpeg"
        entries.append(
            {
                "filename": filename,
                "bytes": timestamped,
                "member_slots": [member_index],
                "quality": {
                    "sharpness": quality[0],
                    "brightness": quality[1],
                    "eyes_open_ratio": quality[2],
                },
                "label": f"{group_label} - {name}",
            }
        )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--album-id", required=True)
    parser.add_argument("--uploader-member-id", required=True, help="기존 멤버 id (새 멤버를 만들지 않는다)")
    parser.add_argument("--session-secret", default="dev-demo-secret-not-for-prod")
    args = parser.parse_args()

    all_entries = []
    for group_label, member_index, source_file, time_prefix, qualities in GROUPS:
        entries = build_group_files(group_label, member_index, source_file, time_prefix, qualities)
        all_entries.extend(entries)

    # manifest 등록
    for entry in all_entries:
        digest, _ = add_sample(
            entry["bytes"],
            source=SOURCE,
            license=LICENSE,
            face_count=1,
            label=entry["label"],
            member_slots=entry["member_slots"],
            quality=entry["quality"],
            force=True,
        )
        print(f"manifest: {digest[:12]}  {entry['label']}")

    # 업로드 — 새 멤버를 만들지 않고, 기존 멤버의 세션 쿠키를 직접 서명해서 쓴다.
    cookie_value = URLSafeSerializer(args.session_secret, salt="zzik-member-session-v1").dumps(
        {"member_id": args.uploader_member_id}
    )
    with httpx.Client(base_url=args.base_url, timeout=30.0, cookies={"zzik_session": cookie_value}) as client:
        files = [("files", (e["filename"], io.BytesIO(e["bytes"]), "image/jpeg")) for e in all_entries]
        resp = client.post(f"/api/albums/{args.album_id}/photos", files=files)
        resp.raise_for_status()
        batch = resp.json()
        ok = sum(1 for r in batch["results"] if r["ok"])
        print(f"업로드: {ok}/{len(batch['results'])} 성공")
        for r in batch["results"]:
            if not r["ok"]:
                print(f"  실패: {r['filename']} -> {r['error']}")


if __name__ == "__main__":
    sys.exit(main() or 0)
