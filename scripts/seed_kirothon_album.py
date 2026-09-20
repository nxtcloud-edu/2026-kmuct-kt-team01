"""KIROTHON 팀(토큰사냥꾼) 데모 앨범을 실제 API로 만든다.

실행 중인 API(기본 http://127.0.0.1:8001)에 대고 실제 HTTP 요청을 보낸다 — DB를
직접 건드리지 않는다. 앨범 생성 → 멤버 5명 참여 → 멤버별 기준 얼굴(프로필) 등록 →
갤러리 사진 21장 업로드까지 전부 실제 엔드포인트를 거친다. FACE_PROVIDER=mock 이고
scripts/seed_kirothon_manifest.py 로 미리 등록해 둔 사진들이라 mock_source='manifest'
로 결정론적 결과가 나온다.

실행: python -m scripts.seed_kirothon_album [--base-url http://127.0.0.1:8001]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

PHOTO_DIR = Path("/Users/seopseopi/kirothon/사진라벨링 copy")

# (표시 이름, 프로필/기준 얼굴 파일)
MEMBERS = [
    ("유준석", "유준석(본인).jpeg"),
    ("이민섭", "이민섭(본인).jpeg"),
    ("김규태", "김규태(본인).jpeg"),
    ("이상혁", "이상혁(본인).jpeg"),
    ("황연주", "황연주(본인).jpeg"),
]

GALLERY_PHOTOS = [
    "기타.jpeg",
    "기타1.jpeg",
    "기타2.jpeg",
    "기타3.jpeg",
    "기타4.jpeg",
    "기타5.jpeg",
    "기타6.jpeg",
    "음식.jpeg",
    "김규태.jpeg",
    "김규태,유준석.jpeg",
    "유준석.jpeg",
    "유준석,김규태.jpeg",
    "이민섭.jpeg",
    "이상혁.jpeg",
    "이상혁,이민섭.jpeg",
    "이상혁2.jpeg",
    "이상혁3.jpeg",
    "황연주.jpeg",
    "황연주, 김규태.jpeg",
    "황연주,김규태.jpeg",
    "단체사진, 황연주, 유준석, 김규태, 이상혁.jpeg",
]

# 데모용 앨범이라 모든 멤버가 같은 비밀번호를 쓴다. 실제 사용자 계정이 아니다.
DEMO_PASSCODE = "kirothon"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        # 1) 앨범 생성 (첫 멤버 = 유준석)
        creator_name, creator_ref = MEMBERS[0]
        resp = client.post(
            "/api/albums",
            json={
                "name": "KIROTHON 토큰사냥꾼",
                "display_name": creator_name,
                "passcode": DEMO_PASSCODE,
            },
        )
        resp.raise_for_status()
        created = resp.json()
        album_id, invite_code = created["album_id"], created["invite_code"]
        print(f"앨범 생성: {album_id} (초대코드 {invite_code})")

        member_ids: dict[str, str] = {creator_name: created["member_id"]}
        member_cookies: dict[str, httpx.Cookies] = {creator_name: httpx.Cookies(client.cookies)}

        # 2) 나머지 멤버 참여 (각자 새 세션이어야 하므로 매번 쿠키를 비운다)
        for name, _ref in MEMBERS[1:]:
            client.cookies.clear()
            resp = client.post(
                "/api/albums/join",
                json={
                    "invite_code": invite_code,
                    "display_name": name,
                    "passcode": DEMO_PASSCODE,
                },
            )
            resp.raise_for_status()
            joined = resp.json()
            member_ids[name] = joined["member_id"]
            member_cookies[name] = httpx.Cookies(client.cookies)
            print(f"참여: {name} -> {joined['member_id']}")

        # 3) 멤버별 기준 얼굴(프로필) 등록 — 각자 자기 세션으로
        for name, ref_file in MEMBERS:
            client.cookies.clear()
            client.cookies.update(member_cookies[name])
            path = PHOTO_DIR / ref_file
            with open(path, "rb") as fh:
                resp = client.post(
                    "/api/members/me/reference",
                    files={"file": (ref_file, fh, "image/jpeg")},
                )
            resp.raise_for_status()
            print(f"기준 얼굴 등록: {name} -> {resp.json()}")

        # 4) 갤러리 사진 21장 업로드 (업로더: 유준석)
        client.cookies.clear()
        client.cookies.update(member_cookies[creator_name])
        files = []
        opened = []
        for filename in GALLERY_PHOTOS:
            fh = open(PHOTO_DIR / filename, "rb")
            opened.append(fh)
            files.append(("files", (filename, fh, "image/jpeg")))
        try:
            resp = client.post(f"/api/albums/{album_id}/photos", files=files)
        finally:
            for fh in opened:
                fh.close()
        resp.raise_for_status()
        batch = resp.json()
        ok = sum(1 for r in batch["results"] if r["ok"])
        print(f"업로드: {ok}/{len(batch['results'])} 성공")
        for r in batch["results"]:
            if not r["ok"]:
                print(f"  실패: {r['filename']} -> {r['error']}")

        # 5) 분석 완료까지 대기
        deadline = time.time() + 60
        while time.time() < deadline:
            resp = client.get(f"/api/albums/{album_id}/status")
            resp.raise_for_status()
            status = resp.json()
            print(f"분석 상태: {status}")
            if status.get("pending", 0) == 0 and status.get("processing", 0) == 0:
                break
            time.sleep(2)

        print(f"\n완료. album_id={album_id} invite_code={invite_code}")
        print(f"멤버 매핑: {member_ids}")


if __name__ == "__main__":
    sys.exit(main() or 0)
