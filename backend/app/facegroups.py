"""미등록 인물 얼굴 그룹 (역할 4 소유, T3 부가 기능).

analyze() 가 `status == "unregistered"` 로 표시한 얼굴들을 "같은 사람으로 보이는" 묶음으로
모은다. 기준 셀카를 등록하지 않은 사람도 "이 사람 사진 모아보기"가 되게 하는 기능이다.

경계:
  - DB 에 쓰지 않는다. 결과 dict 를 3번이 저장하고 API 로 노출한다.
  - 얼굴 임베딩을 직접 만들지 않는다. Rekognition CompareFaces 가 판단한다.
  - 그룹에 이름을 지어내지 않는다. 라벨은 사람이 붙인다.

그룹 자료구조(3번이 그대로 저장하면 된다):
    {"group_id": str, "face_ids": [str], "representative": str, "labeled_member_id": None}
face_id 는 "<photo_id>:<face_index>" 형식이다.
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Any, Callable, Iterable, Mapping, Sequence

from .quality import AnalysisError, iou, normalize_box

logger = logging.getLogger(__name__)

__all__ = [
    "face_id",
    "group_faces",
    "merge_groups",
    "split_group",
    "move_face",
    "crop_face",
    "make_rekognition_comparer",
    "faces_from_analysis",
    "group_album_faces",
]

_GROUP_NAMESPACE = uuid.UUID("0a5b9b7e-3d21-5c44-8f10-2b6c7d8e9f01")

# 그룹 판정 임계. 등록 인물 매칭(90)보다 보수적으로 둔다. 남의 사진에 엉뚱한 사람을
# 묶는 것이 묶지 않는 것보다 나쁘기 때문이다.
DEFAULT_GROUP_THRESHOLD = 92.0
# 비교 호출 상한. 초과하면 남은 얼굴은 각자 그룹으로 두고 truncated=True 로 알린다.
DEFAULT_MAX_COMPARISONS = 300


def face_id(photo_id: str, face_index: int) -> str:
    return f"{photo_id}:{int(face_index)}"


def _new_group_id(first_face_id: str) -> str:
    return str(uuid.uuid5(_GROUP_NAMESPACE, first_face_id))


# --------------------------------------------------------------------------
# 그룹 만들기
# --------------------------------------------------------------------------
def group_faces(
    faces: Sequence[Mapping[str, Any]],
    compare: Callable[[Mapping[str, Any], Mapping[str, Any]], float | None],
    *,
    threshold: float = DEFAULT_GROUP_THRESHOLD,
    max_comparisons: int = DEFAULT_MAX_COMPARISONS,
) -> dict[str, Any]:
    """미등록 얼굴들을 그룹으로 묶는다.

    faces: [{"photo_id", "face_index", ...}] — analyze() 의 unregistered 얼굴들.
           정렬 순서가 결과를 결정하므로 호출자가 안정적인 순서로 넘긴다.
    compare(a, b) -> similarity(0~100) 또는 None
           비교 방법을 주입받는다. 실제 호출은 make_rekognition_comparer 가 한다.
           None 을 돌려주면 "판단 불가"로 보고 묶지 않는다.

    각 얼굴을 기존 그룹의 대표 얼굴하고만 비교한다(단일 연결). 그래서 호출 수는
    최악의 경우 얼굴 수 × 그룹 수이고, max_comparisons 로 상한을 건다.

    반환: {groups, ungrouped, comparisons, truncated, failures, threshold}
    """
    ordered = [dict(f) for f in faces or []]
    groups: list[dict[str, Any]] = []
    comparisons = 0
    truncated = False
    failures: list[dict[str, str]] = []

    for item in ordered:
        fid = face_id(item["photo_id"], item["face_index"])
        placed = False

        for group in groups:
            if comparisons >= max_comparisons:
                truncated = True
                break
            representative = group["_representative_face"]
            # 같은 사진 안의 서로 다른 얼굴은 같은 사람일 수 없다.
            if representative["photo_id"] == item["photo_id"]:
                continue
            comparisons += 1
            try:
                similarity = compare(representative, item)
            except AnalysisError as exc:
                failures.append({"face_id": fid, "reason": exc.code})
                similarity = None
                if not exc.retryable and exc.code == "AWS_AUTH":
                    raise
            if similarity is not None and similarity >= threshold:
                group["face_ids"].append(fid)
                group["similarities"].append(round(float(similarity), 4))
                placed = True
                break

        if not placed:
            groups.append(
                {
                    "group_id": _new_group_id(fid),
                    "face_ids": [fid],
                    "similarities": [],
                    "representative": fid,
                    "labeled_member_id": None,
                    "_representative_face": item,
                }
            )

    for group in groups:
        group.pop("_representative_face", None)

    # 혼자 있는 그룹은 "같은 사람을 두 번 이상 본 적 없음"이다. 그룹이라 부르지 않는다.
    real_groups = [g for g in groups if len(g["face_ids"]) > 1]
    ungrouped = [g["face_ids"][0] for g in groups if len(g["face_ids"]) == 1]

    return {
        "groups": real_groups,
        "ungrouped": ungrouped,
        "comparisons": comparisons,
        "truncated": truncated,
        "failures": failures,
        "threshold": threshold,
    }


# --------------------------------------------------------------------------
# 사람이 고치는 연산 — 전부 순수 함수다
# --------------------------------------------------------------------------
def _find(groups: Sequence[Mapping[str, Any]], group_id: str) -> Mapping[str, Any]:
    for group in groups:
        if group["group_id"] == group_id:
            return group
    raise AnalysisError(
        "GROUP_NOT_FOUND",
        "인물 그룹을 찾을 수 없습니다",
        retryable=False,
        details={"group_id": group_id},
    )


def merge_groups(
    groups: Sequence[Mapping[str, Any]], keep_id: str, merge_id: str
) -> list[dict[str, Any]]:
    """두 그룹을 하나로 합친다. 같은 사람인데 나뉘어 있을 때 쓴다."""
    if keep_id == merge_id:
        raise AnalysisError("GROUP_SAME", "같은 그룹끼리는 합칠 수 없습니다", retryable=False)
    keep, merge = _find(groups, keep_id), _find(groups, merge_id)

    labels = {keep.get("labeled_member_id"), merge.get("labeled_member_id")} - {None}
    if len(labels) > 1:
        raise AnalysisError(
            "GROUP_LABEL_CONFLICT",
            "서로 다른 인물로 지정된 그룹은 합칠 수 없습니다",
            retryable=False,
            details={"group_ids": [keep_id, merge_id]},
        )

    result: list[dict[str, Any]] = []
    for group in groups:
        if group["group_id"] == merge_id:
            continue
        if group["group_id"] == keep_id:
            merged_ids = list(dict.fromkeys([*keep["face_ids"], *merge["face_ids"]]))
            result.append(
                {
                    **dict(keep),
                    "face_ids": merged_ids,
                    "representative": keep.get("representative") or merged_ids[0],
                    "labeled_member_id": next(iter(labels), None),
                }
            )
        else:
            result.append(dict(group))
    return result


def split_group(
    groups: Sequence[Mapping[str, Any]], group_id: str, face_ids: Iterable[str]
) -> list[dict[str, Any]]:
    """그룹에서 일부 얼굴을 떼어 새 그룹으로 만든다. 다른 사람이 섞였을 때 쓴다."""
    source = _find(groups, group_id)
    moving = [fid for fid in dict.fromkeys(face_ids) if fid in source["face_ids"]]
    if not moving:
        raise AnalysisError(
            "GROUP_SPLIT_EMPTY",
            "분리할 얼굴을 그룹에서 찾지 못했습니다",
            retryable=False,
            details={"group_id": group_id},
        )
    remaining = [fid for fid in source["face_ids"] if fid not in moving]
    if not remaining:
        raise AnalysisError(
            "GROUP_SPLIT_ALL",
            "그룹의 모든 얼굴을 분리할 수는 없습니다",
            retryable=False,
            details={"group_id": group_id},
        )

    result: list[dict[str, Any]] = []
    for group in groups:
        if group["group_id"] != group_id:
            result.append(dict(group))
            continue
        result.append(
            {
                **dict(source),
                "face_ids": remaining,
                "representative": (
                    source.get("representative")
                    if source.get("representative") in remaining
                    else remaining[0]
                ),
            }
        )
        result.append(
            {
                "group_id": _new_group_id(moving[0]),
                "face_ids": moving,
                "similarities": [],
                "representative": moving[0],
                # 떼어낸 쪽은 아직 누구인지 모른다. 원래 라벨을 물려주지 않는다.
                "labeled_member_id": None,
            }
        )
    return result


def move_face(
    groups: Sequence[Mapping[str, Any]], face: str, target_group_id: str
) -> list[dict[str, Any]]:
    """얼굴 하나를 다른 그룹으로 옮긴다. 옮기고 비면 그 그룹은 사라진다."""
    _find(groups, target_group_id)
    result: list[dict[str, Any]] = []
    for group in groups:
        face_ids = [fid for fid in group["face_ids"] if fid != face]
        if group["group_id"] == target_group_id:
            face_ids = list(dict.fromkeys([*face_ids, face]))
        if not face_ids:
            continue
        representative = group.get("representative")
        result.append(
            {
                **dict(group),
                "face_ids": face_ids,
                "representative": representative if representative in face_ids else face_ids[0],
            }
        )
    return result


# --------------------------------------------------------------------------
# 실제 비교 — Rekognition CompareFaces
# --------------------------------------------------------------------------
def crop_face(image_bytes: bytes, box: Mapping[str, Any], margin: float = 0.25) -> bytes:
    """얼굴 박스를 여유를 두고 잘라 낸다. CompareFaces 원본 이미지로 쓴다.

    원본 바이트를 여러 벌 들고 있지 않도록 잘라 낸 결과만 돌려준다(t3.small, RAM 2GB).
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "DEPENDENCY_MISSING", "Pillow 가 설치되어 있지 않습니다", retryable=False
        ) from exc

    area = normalize_box(box)
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(image_bytes)) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        width, height = source.size
        pad_x = area["width"] * margin
        pad_y = area["height"] * margin
        left = max(0, int((area["left"] - pad_x) * width))
        top = max(0, int((area["top"] - pad_y) * height))
        right = min(width, int((area["left"] + area["width"] + pad_x) * width))
        bottom = min(height, int((area["top"] + area["height"] + pad_y) * height))
        if right - left < 1 or bottom - top < 1:
            raise AnalysisError(
                "FACE_CROP_FAILED", "얼굴 영역을 잘라 내지 못했습니다", retryable=False
            )
        source.crop((left, top, right, bottom)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def make_rekognition_comparer(
    load_image: Callable[[str], bytes],
    *,
    settings: Any | None = None,
    client: Any | None = None,
) -> Callable[[Mapping[str, Any], Mapping[str, Any]], float | None]:
    """group_faces 에 넘길 실제 비교 함수를 만든다.

    load_image(photo_key) -> bytes 는 3번의 Storage.get 을 그대로 넘기면 된다.
    각 얼굴 dict 에는 photo_id, face_index, box, photo_key 가 있어야 한다.

    얼굴 크롭은 photo_key 당 한 번만 만들어 캐시한다(같은 사진의 대표 얼굴을 반복해서
    자르지 않게). 캐시는 이 comparer 가 사는 동안만 유지된다.
    """
    from . import analysis as _analysis

    settings = settings or _analysis.load_settings()
    if settings.provider != _analysis.PROVIDER_REKOGNITION:
        raise AnalysisError(
            "CONFIG_INVALID",
            "얼굴 그룹은 FACE_PROVIDER=rekognition 에서만 동작합니다",
            retryable=False,
            details={"face_provider": settings.provider},
        )
    client = client or _analysis._rekognition_client(settings.region)
    crops: dict[str, bytes] = {}

    def _crop_of(face: Mapping[str, Any]) -> bytes:
        key = face_id(face["photo_id"], face["face_index"])
        if key not in crops:
            crops[key] = crop_face(load_image(face["photo_key"]), face["box"])
        return crops[key]

    def compare(source: Mapping[str, Any], target: Mapping[str, Any]) -> float | None:
        try:
            response = _analysis._call(
                client,
                "CompareFaces",
                "compare_faces",
                SourceImage={"Bytes": _crop_of(source)},
                TargetImage={"Bytes": _crop_of(target)},
                SimilarityThreshold=DEFAULT_GROUP_THRESHOLD - 5.0,
                QualityFilter="AUTO",
            )
        except AnalysisError as exc:
            if exc.code in {"INVALID_PARAMETER", "INVALID_IMAGE", "IMAGE_TOO_SMALL"}:
                # 크롭이 너무 작거나 얼굴이 안 잡히는 경우. 묶지 않고 넘어간다.
                return None
            raise
        matches = response.get("FaceMatches") or []
        if not matches:
            return None
        # 크롭 안에 얼굴이 하나뿐이므로 가장 큰 유사도를 쓴다.
        return max(float(m.get("Similarity") or 0.0) for m in matches)

    return compare


def faces_from_analysis(photo_id: str, photo_key: str, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """analyze() 결과에서 미등록 얼굴만 꺼내 group_faces 입력 형태로 바꾼다."""
    faces = []
    for index, face in enumerate(result.get("faces") or []):
        if face.get("status") != "unregistered":
            continue
        faces.append(
            {
                "photo_id": photo_id,
                "photo_key": photo_key,
                "face_index": index,
                "box": face.get("box") or {},
            }
        )
    return faces


def overlaps_known_face(box_a: Mapping[str, Any], box_b: Mapping[str, Any]) -> bool:
    """같은 사진 안에서 이미 아는 얼굴과 같은 자리인지 본다(중복 등록 방지)."""
    return iou(box_a, box_b) >= 0.4


# --------------------------------------------------------------------------
# 앨범 단위 진입점 — 3번이 붙일 때 쓰는 함수
# --------------------------------------------------------------------------
def group_album_faces(
    photos: Sequence[Mapping[str, Any]],
    load_image: Callable[[str], bytes],
    *,
    settings: Any | None = None,
    client: Any | None = None,
    threshold: float = DEFAULT_GROUP_THRESHOLD,
    max_comparisons: int = DEFAULT_MAX_COMPARISONS,
) -> dict[str, Any]:
    """앨범 1개의 미등록 얼굴을 묶는다. 3번은 이 함수 하나만 부르면 된다.

    photos: 분석이 끝난 사진들. 각 항목에 필요한 것은 세 개뿐이다.
        {"id": <photo id>, "s3_key": <원본 키>, "faces": <analyze() 의 faces 그대로>}
        DB 에서 꺼낼 때 faces 를 보관하지 않았다면 재분석 없이는 쓸 수 없다.
        (photos 테이블에 faces 원본을 저장하지 않는다면, worker 가 analyze 결과를
         그대로 넘겨 주는 경로가 필요하다. 그 판단은 3번 몫이다.)

    load_image: Storage.get 을 그대로 넘기면 된다.

    반환은 group_faces 와 같고 `photo_count`, `face_count` 가 더 붙는다.
    DB 에 쓰지 않는다. 저장은 3번이 한다.

    FACE_PROVIDER=mock 이면 CONFIG_INVALID 로 거절한다. 가짜 인물 그룹을 만들어
    화면에 보여주지 않기 위해서다.
    """
    faces: list[dict[str, Any]] = []
    for photo in photos or []:
        photo_id = str(photo.get("id") or "")
        photo_key = str(photo.get("s3_key") or "")
        if not photo_id or not photo_key:
            continue
        faces.extend(faces_from_analysis(photo_id, photo_key, photo))

    if not faces:
        return {
            "groups": [],
            "ungrouped": [],
            "comparisons": 0,
            "truncated": False,
            "failures": [],
            "threshold": threshold,
            "photo_count": len(photos or []),
            "face_count": 0,
        }

    compare = make_rekognition_comparer(load_image, settings=settings, client=client)
    result = group_faces(
        faces, compare, threshold=threshold, max_comparisons=max_comparisons
    )
    result["photo_count"] = len(photos or [])
    result["face_count"] = len(faces)
    return result
