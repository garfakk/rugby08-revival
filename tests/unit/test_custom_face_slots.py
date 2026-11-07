"""backend.game_specific_variables.face_id_for_custom_faces: the game loads a
custom head from the archive file named md5("players/heads/<face id>"), so
each slot's filename must match its face id, or the player falls back to the
generic face (666)."""
import hashlib

from backend import game_specific_variables as gsv


def test_slot_filenames_match_face_ids():
    for team, faces in gsv.face_id_for_custom_faces.items():
        assert len(faces) == 22, team
        for shirt, face in enumerate(faces, 1):
            want = hashlib.md5(f"players/heads/{face['face_id']}".encode()).hexdigest() + ".big"
            assert face["filename"] == want, (team, shirt, face)


def test_slots_are_distinct():
    faces = [f for team in gsv.face_id_for_custom_faces.values() for f in team]
    assert len({f["face_id"] for f in faces}) == len(faces)
    assert len({f["filename"] for f in faces}) == len(faces)
