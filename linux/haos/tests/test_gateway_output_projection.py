"""Whole-event file selection preserves code fences across durable chunk edges."""
import pytest
from haos.gateway_output_projection import project


def test_cross_chunk_fence_does_not_export_literal_example_or_drop_its_text():
    chunks=['Intro\n```text\nMEDIA:/literal/example.txt\n','```\nSummary\nMEDIA:./actual.pdf\nDone\n']
    selected=project(chunks)
    assert selected==[{'text':chunks[0],'paths':[]},{'text':'```\nSummary\nDone\n','paths':['./actual.pdf']}]
    assert ''.join(row['text'] for row in selected)=='Intro\n```text\nMEDIA:/literal/example.txt\n```\nSummary\nDone\n'


def test_real_marker_straddling_original_chunk_is_refused_instead_of_guessing_path():
    with pytest.raises(ValueError):project(['Text\nMEDIA:./res','ult.pdf\nEnd'])


def test_voice_and_document_markers_are_removed_without_losing_original_whitespace():
    chunks=['  Start\n[[audio_as_voice]]\nMEDIA:./reply.ogg\n','\n[[as_document]]\nEnd  \n']
    assert project(chunks)==[{'text':'  Start\n','paths':['./reply.ogg']},{'text':'\nEnd  \n','paths':[]}]


def test_two_complete_files_stay_bound_to_their_original_chunks():
    assert project(['A\nMEDIA:/agent/report.csv\n','B\nMEDIA:./cover.png\n'])==[
        {'text':'A\n','paths':['/agent/report.csv']},{'text':'B\n','paths':['./cover.png']}]


def test_repeated_marker_keeps_only_first_source_snapshot_without_exposing_the_path():
    assert project(['A\nMEDIA:./result.csv\n','B\nMEDIA:./result.csv\n'])==[
        {'text':'A\n','paths':['./result.csv']},{'text':'B\n','paths':[]}]
