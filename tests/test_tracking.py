from app.tracking import ByteTrackAdapter
from app.vision import Detection


def test_bytetrack_preserves_id_for_a_continuous_detection() -> None:
    tracker = ByteTrackAdapter(frame_rate=5)
    first = Detection("person", 0, 0.9, (10, 10, 80, 100))
    next_frame = Detection("person", 0, 0.88, (12, 11, 82, 101))

    first_result = tracker.update([first])
    next_result = tracker.update([next_frame])

    assert len(first_result) == 1
    assert len(next_result) == 1
    assert first_result[0].track_id == next_result[0].track_id
    assert next_result[0].detection == next_frame
