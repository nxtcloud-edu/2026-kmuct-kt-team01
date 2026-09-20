"""facegroups.py 테스트 (역할 4, T3 미등록 인물 그룹).

비교 함수를 주입해서 검사하므로 AWS 를 호출하지 않는다.
실제 Rekognition 으로 묶은 정확도는 측정하지 않았다(미측정).
"""

from __future__ import annotations

import pytest

from backend.app.facegroups import (
    DEFAULT_GROUP_THRESHOLD,
    AnalysisError,
    crop_face,
    face_id,
    faces_from_analysis,
    group_faces,
    merge_groups,
    move_face,
    split_group,
)
from tests.conftest import make_image


def face(photo_id, index=0, person=None):
    """person 은 테스트용 정답 라벨이다. 비교 함수가 이걸 보고 유사도를 낸다."""
    return {
        "photo_id": photo_id,
        "photo_key": f"albums/a/photos/{photo_id}/original.jpg",
        "face_index": index,
        "box": {"left": 0.1 + 0.2 * index, "top": 0.1, "width": 0.15, "height": 0.2},
        "person": person,
    }


def truth_compare(a, b):
    """같은 person 이면 96, 아니면 40."""
    if a.get("person") is None or b.get("person") is None:
        return None
    return 96.0 if a["person"] == b["person"] else 40.0


# --------------------------------------------------------------------------
# 그룹 만들기
# --------------------------------------------------------------------------
def test_same_person_across_photos_is_grouped():
    faces = [face("p1", 0, "A"), face("p2", 0, "A"), face("p3", 0, "B")]
    result = group_faces(faces, truth_compare)

    assert len(result["groups"]) == 1
    assert result["groups"][0]["face_ids"] == ["p1:0", "p2:0"]
    assert result["ungrouped"] == ["p3:0"]
    assert result["groups"][0]["labeled_member_id"] is None  # 이름을 지어내지 않는다


def test_two_faces_in_the_same_photo_are_never_grouped():
    """한 사진에 동시에 찍힌 두 얼굴은 같은 사람일 수 없다."""
    faces = [face("p1", 0, "A"), face("p1", 1, "A")]
    result = group_faces(faces, truth_compare)
    assert result["groups"] == []
    assert sorted(result["ungrouped"]) == ["p1:0", "p1:1"]
    assert result["comparisons"] == 0


def test_similarity_below_threshold_does_not_group():
    def weak(a, b):
        return DEFAULT_GROUP_THRESHOLD - 0.1

    result = group_faces([face("p1", 0, "A"), face("p2", 0, "A")], weak)
    assert result["groups"] == []


def test_undecidable_comparison_does_not_group():
    result = group_faces([face("p1"), face("p2")], lambda a, b: None)
    assert result["groups"] == []
    assert len(result["ungrouped"]) == 2


def test_comparison_budget_is_respected_and_reported():
    faces = [face(f"p{i}", 0, f"person{i}") for i in range(10)]
    result = group_faces(faces, truth_compare, max_comparisons=3)
    assert result["comparisons"] <= 3
    assert result["truncated"] is True


def test_grouping_is_deterministic():
    faces = [face("p1", 0, "A"), face("p2", 0, "B"), face("p3", 0, "A")]
    assert group_faces(faces, truth_compare) == group_faces(faces, truth_compare)


def test_group_ids_are_stable_for_the_same_first_face():
    faces = [face("p1", 0, "A"), face("p2", 0, "A")]
    first = group_faces(faces, truth_compare)["groups"][0]["group_id"]
    second = group_faces(faces, truth_compare)["groups"][0]["group_id"]
    assert first == second


def test_retryable_comparison_failure_is_recorded_not_fatal():
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        raise AnalysisError("AWS_THROTTLED", "지연", retryable=True)

    result = group_faces([face("p1", 0, "A"), face("p2", 0, "A")], flaky)
    assert result["groups"] == []
    assert result["failures"] == [{"face_id": "p2:0", "reason": "AWS_THROTTLED"}]


def test_auth_failure_stops_grouping():
    def denied(a, b):
        raise AnalysisError("AWS_AUTH", "AWS 분석 권한을 확인해 주세요", retryable=False)

    with pytest.raises(AnalysisError) as err:
        group_faces([face("p1", 0, "A"), face("p2", 0, "A")], denied)
    assert err.value.code == "AWS_AUTH"


# --------------------------------------------------------------------------
# 사람이 고치는 연산
# --------------------------------------------------------------------------
def groups_fixture():
    return [
        {"group_id": "g1", "face_ids": ["p1:0", "p2:0"], "similarities": [96.0],
         "representative": "p1:0", "labeled_member_id": None},
        {"group_id": "g2", "face_ids": ["p3:0", "p4:0"], "similarities": [95.0],
         "representative": "p3:0", "labeled_member_id": None},
    ]


def test_merge_joins_face_ids_without_duplicates():
    merged = merge_groups(groups_fixture(), "g1", "g2")
    assert len(merged) == 1
    assert merged[0]["group_id"] == "g1"
    assert merged[0]["face_ids"] == ["p1:0", "p2:0", "p3:0", "p4:0"]


def test_merge_keeps_the_single_label():
    groups = groups_fixture()
    groups[1]["labeled_member_id"] = "member-9"
    merged = merge_groups(groups, "g1", "g2")
    assert merged[0]["labeled_member_id"] == "member-9"


def test_merging_two_differently_labeled_groups_is_refused():
    groups = groups_fixture()
    groups[0]["labeled_member_id"] = "member-1"
    groups[1]["labeled_member_id"] = "member-2"
    with pytest.raises(AnalysisError) as err:
        merge_groups(groups, "g1", "g2")
    assert err.value.code == "GROUP_LABEL_CONFLICT"


def test_merge_with_unknown_group_is_reported():
    with pytest.raises(AnalysisError) as err:
        merge_groups(groups_fixture(), "g1", "nope")
    assert err.value.code == "GROUP_NOT_FOUND"


def test_split_creates_a_new_unlabeled_group():
    groups = groups_fixture()
    groups[0]["face_ids"] = ["p1:0", "p2:0", "p5:0"]
    groups[0]["labeled_member_id"] = "member-1"
    result = split_group(groups, "g1", ["p5:0"])

    kept = next(g for g in result if g["group_id"] == "g1")
    new = next(g for g in result if g["face_ids"] == ["p5:0"])
    assert kept["face_ids"] == ["p1:0", "p2:0"]
    assert kept["labeled_member_id"] == "member-1"
    # 떼어낸 쪽은 아직 누구인지 모른다
    assert new["labeled_member_id"] is None


def test_split_that_empties_the_group_is_refused():
    with pytest.raises(AnalysisError) as err:
        split_group(groups_fixture(), "g1", ["p1:0", "p2:0"])
    assert err.value.code == "GROUP_SPLIT_ALL"


def test_split_with_faces_not_in_the_group_is_refused():
    with pytest.raises(AnalysisError) as err:
        split_group(groups_fixture(), "g1", ["p9:0"])
    assert err.value.code == "GROUP_SPLIT_EMPTY"


def test_move_face_between_groups_and_repoint_representative():
    result = move_face(groups_fixture(), "p1:0", "g2")
    g1 = next(g for g in result if g["group_id"] == "g1")
    g2 = next(g for g in result if g["group_id"] == "g2")
    assert g1["face_ids"] == ["p2:0"]
    assert g1["representative"] == "p2:0"  # 대표가 빠져나가면 남은 얼굴로 옮긴다
    assert g2["face_ids"] == ["p3:0", "p4:0", "p1:0"]


def test_group_disappears_when_its_last_face_moves_out():
    groups = [
        {"group_id": "g1", "face_ids": ["p1:0"], "representative": "p1:0",
         "similarities": [], "labeled_member_id": None},
        {"group_id": "g2", "face_ids": ["p2:0"], "representative": "p2:0",
         "similarities": [], "labeled_member_id": None},
    ]
    result = move_face(groups, "p1:0", "g2")
    assert [g["group_id"] for g in result] == ["g2"]
    assert result[0]["face_ids"] == ["p2:0", "p1:0"]


# --------------------------------------------------------------------------
# analyze() 결과 연결 / 크롭
# --------------------------------------------------------------------------
def test_only_unregistered_faces_are_collected():
    result = {
        "faces": [
            {"status": "matched", "member_id": "m1", "box": {"left": 0.1, "top": 0.1, "width": 0.1, "height": 0.1}},
            {"status": "unregistered", "member_id": None, "box": {"left": 0.5, "top": 0.1, "width": 0.1, "height": 0.1}},
            {"status": "uncertain", "member_id": None, "box": {"left": 0.7, "top": 0.1, "width": 0.1, "height": 0.1}},
        ]
    }
    faces = faces_from_analysis("p1", "albums/a/photos/p1/original.jpg", result)
    assert len(faces) == 1
    assert faces[0]["face_index"] == 1
    assert face_id(faces[0]["photo_id"], faces[0]["face_index"]) == "p1:1"


def test_crop_face_returns_a_smaller_jpeg():
    from backend.app.quality import inspect_image

    image = make_image(width=800, height=600)
    cropped = crop_face(image, {"left": 0.25, "top": 0.25, "width": 0.2, "height": 0.2})
    info = inspect_image(cropped)
    assert info.mime == "image/jpeg"
    assert info.width < 800 and info.height < 600


def test_crop_face_rejects_a_zero_sized_box():
    with pytest.raises(AnalysisError) as err:
        crop_face(make_image(), {"left": 0.0, "top": 0.0, "width": 0.0, "height": 0.0})
    assert err.value.code == "FACE_CROP_FAILED"


# --------------------------------------------------------------------------
# 앨범 단위 진입점 (3번이 붙일 때 쓰는 함수)
# --------------------------------------------------------------------------
from backend.app.facegroups import group_album_faces  # noqa: E402


def analyzed_photo(photo_id: str, statuses: list[str]):
    return {
        "id": photo_id,
        "s3_key": f"albums/a/photos/{photo_id}/original.jpg",
        "faces": [
            {
                "status": status,
                "member_id": "m1" if status == "matched" else None,
                "box": {"left": 0.1 + 0.2 * i, "top": 0.1, "width": 0.15, "height": 0.2},
            }
            for i, status in enumerate(statuses)
        ],
    }


def test_album_entry_point_returns_empty_without_calling_aws(monkeypatch):
    """미등록 얼굴이 없으면 comparer 를 만들지도 않는다(AWS 호출 0회)."""
    from backend.app import facegroups

    monkeypatch.setattr(
        facegroups,
        "make_rekognition_comparer",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("불러서는 안 된다")),
    )
    photos = [analyzed_photo("p1", ["matched", "uncertain"])]
    result = group_album_faces(photos, lambda key: b"")

    assert result["groups"] == []
    assert result["face_count"] == 0
    assert result["photo_count"] == 1
    assert result["comparisons"] == 0


def test_album_entry_point_collects_only_unregistered_faces(monkeypatch):
    from backend.app import facegroups

    seen = {}

    def fake_comparer(load_image, *, settings=None, client=None):
        seen["load_image"] = load_image
        return truth_compare

    monkeypatch.setattr(facegroups, "make_rekognition_comparer", fake_comparer)
    photos = [
        analyzed_photo("p1", ["matched", "unregistered"]),
        analyzed_photo("p2", ["unregistered"]),
    ]
    loader = lambda key: b""
    result = group_album_faces(photos, loader)

    assert result["face_count"] == 2          # matched 는 빠진다
    assert result["photo_count"] == 2
    assert seen["load_image"] is loader       # Storage.get 을 그대로 넘긴다


def test_album_entry_point_skips_rows_without_id_or_key(monkeypatch):
    from backend.app import facegroups

    monkeypatch.setattr(facegroups, "make_rekognition_comparer", lambda *a, **k: truth_compare)
    broken = {"id": "", "s3_key": "", "faces": [{"status": "unregistered", "box": {}}]}
    result = group_album_faces([broken], lambda key: b"")
    assert result["face_count"] == 0


def test_album_entry_point_refuses_mock_provider(monkeypatch):
    """mock 모드에서는 가짜 인물 그룹을 만들지 않는다."""
    from backend.app.analysis import load_settings

    photos = [analyzed_photo("p1", ["unregistered"]), analyzed_photo("p2", ["unregistered"])]
    with pytest.raises(AnalysisError) as err:
        group_album_faces(
            photos, lambda key: b"", settings=load_settings({"FACE_PROVIDER": "mock"})
        )
    assert err.value.code == "CONFIG_INVALID"
