from pathlib import Path

import pytest

from polybtc.shadow.csv_tail_vnext import (
    InvalidCSV,
    SourceChanged,
    VNextCSVTailer,
)


HEADER = b"observed_at,market_id,btc_price\n"
ROW_A = b"2026-10-09T12:00:00Z,market-a,40000\n"
ROW_B = b"2026-10-09T12:00:01Z,market-a,40001\n"


def tailer(tmp_path, startup="beginning"):
    source = tmp_path / "collector.csv"
    state = tmp_path / "tail.sqlite3"

    return VNextCSVTailer(
        csv_path=source,
        state_path=state,
        startup=startup,
    )


def test_reads_complete_rows(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A + ROW_B)

    worker = tailer(tmp_path)
    batch = worker.poll()

    assert len(batch.rows) == 2
    assert batch.rows[0].values["market_id"] == "market-a"
    assert batch.rows[1].values["btc_price"] == "40001"

    worker.ack(batch)

    assert worker.poll().rows == ()


def test_incomplete_trailing_row_waits(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A + ROW_B[:-3])

    worker = tailer(tmp_path)

    first = worker.poll()

    assert len(first.rows) == 1
    worker.ack(first)

    with source.open("ab") as file:
        file.write(ROW_B[-3:])

    second = worker.poll()

    assert len(second.rows) == 1
    assert second.rows[0].values["btc_price"] == "40001"


def test_restart_resumes_from_ack(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    original = tailer(tmp_path)
    batch = original.poll()

    original.ack(batch)

    with source.open("ab") as file:
        file.write(ROW_B)

    reopened = tailer(tmp_path)
    next_batch = reopened.poll()

    assert len(next_batch.rows) == 1
    assert next_batch.rows[0].values["btc_price"] == "40001"


def test_unacknowledged_rows_are_replayed(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    first = tailer(tmp_path)
    batch = first.poll()

    # Simulate process interruption before ACK.
    reopened = tailer(tmp_path)
    replayed = reopened.poll()

    assert len(replayed.rows) == 1
    assert replayed.rows[0].row_id == batch.rows[0].row_id


def test_first_start_can_skip_history(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    worker = tailer(tmp_path, startup="end")

    assert worker.poll().rows == ()

    with source.open("ab") as file:
        file.write(ROW_B)

    batch = worker.poll()

    assert len(batch.rows) == 1
    assert batch.rows[0].values["btc_price"] == "40001"


def test_truncation_fails_closed(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    worker = tailer(tmp_path)
    worker.ack(worker.poll())

    source.write_bytes(HEADER)

    with pytest.raises(SourceChanged):
        worker.poll()


@pytest.mark.parametrize("replacement_exists", [True, False])
def test_wrong_source_reports_resume_path_and_preserves_checkpoint(tmp_path, replacement_exists):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)
    worker = tailer(tmp_path)
    worker.ack(worker.poll())
    saved = dict(worker._state())

    replacement = tmp_path / "different.csv"
    if replacement_exists:
        replacement.write_bytes(source.read_bytes())
    wrong = VNextCSVTailer(csv_path=replacement, state_path=worker.state_path)
    with pytest.raises(SourceChanged) as caught:
        wrong.poll()
    assert str(source.resolve()) in str(caught.value)
    assert str(replacement.resolve()) in str(caught.value)
    assert "Do not delete" in str(caught.value)
    assert dict(worker._state()) == saved

    with source.open("ab") as file:
        file.write(ROW_B)
    resumed = tailer(tmp_path)
    batch = resumed.poll()
    assert len(batch.rows) == 1
    assert batch.rows[0].values["btc_price"] == "40001"
    resumed.ack(batch)
    assert resumed.poll().rows == ()


def test_ack_does_not_accept_modified_batch(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    worker = tailer(tmp_path)
    batch = worker.poll()

    # Same-sized replacement with changed content.
    source.write_bytes(HEADER + ROW_A.replace(b"40000", b"49999"))

    with pytest.raises(SourceChanged):
        worker.ack(batch)


def test_duplicate_ack_rejected(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    worker = tailer(tmp_path)
    batch = worker.poll()

    worker.ack(batch)

    with pytest.raises(RuntimeError):
        worker.ack(batch)


def test_column_mismatch_fails_closed(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + b"2026-10-09T12:00:00Z,market-a\n")

    worker = tailer(tmp_path)

    with pytest.raises(InvalidCSV):
        worker.poll()


def test_header_change_fails_closed(tmp_path):
    source = tmp_path / "collector.csv"
    source.write_bytes(HEADER + ROW_A)

    worker = tailer(tmp_path)
    worker.poll()

    source.write_bytes(HEADER.replace(b"btc_price", b"btc_value") + ROW_A)

    with pytest.raises(SourceChanged):
        worker.poll()
