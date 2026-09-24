"""The Nemotron planner fallback (NGE_PLAN_FALLBACK=nemotron).

It had no tests and parsed the reply with a bare `json.loads` on the whole
text, which handles exactly one of the shapes a model answers with. Measured:
four of five realistic replies were silently dropped, a ```json fence - the
likeliest of them - among them.
"""
import pytest

from nge import planner
from nge.backends import nebius

TOOLS = ["bash", "read_file", "edit_file", "write_file"]


def _reply(content):
    return lambda messages, model, tools=None, max_tokens=None: {"content": content}


@pytest.mark.parametrize("content,expected", [
    ('["bash", "read_file"]',                    ["bash", "read_file"]),
    ('```json\n["bash", "read_file"]\n```',      ["bash", "read_file"]),
    ('```\n["bash"]\n```',                       ["bash"]),
    ('Here is the plan:\n["bash", "edit_file"]', ["bash", "edit_file"]),
    ('The plan is ["bash"] — run it.',           ["bash"]),
])
def test_the_shapes_a_model_actually_answers_with(monkeypatch, content, expected):
    monkeypatch.setattr(nebius, "chat_nebius", _reply(content))
    assert nebius.nemotron_plan_fallback("t", TOOLS) == expected


@pytest.mark.parametrize("content", ["", "   ", "I cannot plan this.",
                                     "{}", "[", "[1, 2, 3]"])
def test_unusable_replies_yield_none(monkeypatch, content):
    monkeypatch.setattr(nebius, "chat_nebius", _reply(content))
    assert nebius.nemotron_plan_fallback("t", TOOLS) is None


def test_hallucinated_tools_are_dropped(monkeypatch):
    """The executor only knows the fixed vocabulary; an invented name would
    fail downstream instead of here."""
    monkeypatch.setattr(nebius, "chat_nebius",
                        _reply('["bash", "deploy_to_prod", "read_file"]'))
    assert nebius.nemotron_plan_fallback("t", TOOLS) == ["bash", "read_file"]


def test_a_plan_of_only_invented_tools_is_no_plan(monkeypatch):
    monkeypatch.setattr(nebius, "chat_nebius", _reply('["deploy", "ssh_in"]'))
    assert nebius.nemotron_plan_fallback("t", TOOLS) is None


def test_a_raising_model_does_not_break_planning(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("504")
    monkeypatch.setattr(nebius, "chat_nebius", boom)
    assert nebius.nemotron_plan_fallback("t", TOOLS) is None


# -- wired into the planner --------------------------------------------------

def test_planner_uses_the_fallback_and_marks_it_degraded(monkeypatch, tmp_path):
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    monkeypatch.setattr(nebius, "chat_nebius", _reply('["bash", "write_file"]'))

    r = planner.plan("anything", allow_nemotron=True)
    assert r.names == ["bash", "write_file"]
    assert r.source == "nemotron"
    assert r.degraded is True, "not the 324M planner - say so"


def test_planner_falls_through_to_the_heuristic_when_nemotron_has_nothing(
        monkeypatch, tmp_path):
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    monkeypatch.setattr(nebius, "chat_nebius", _reply("no idea"))

    r = planner.plan("Run the pytest suite", allow_nemotron=True)
    assert r.source == "heuristic" and r.degraded is True


def test_the_fallback_is_off_unless_asked(monkeypatch, tmp_path):
    """It costs a Nemotron call, so it must not fire by default."""
    monkeypatch.delenv("NGE_PLAN_FALLBACK", raising=False)
    monkeypatch.setenv("NODUS_PLAN_CKPT", str(tmp_path / "absent.pt"))
    called = []
    monkeypatch.setattr(nebius, "chat_nebius",
                        lambda *a, **k: called.append(1) or {"content": "[]"})

    r = planner.plan("anything")
    assert called == [], "no cloud call unless NGE_PLAN_FALLBACK=nemotron"
    assert r.source == "heuristic"
