"""Mission parser: engineer's natural language → orchestrator scenario."""
import pytest

from nge.mission import Mission, parse_mission


def test_empty_mission_fails():
    with pytest.raises(ValueError, match="empty"):
        parse_mission("")


def test_defaults():
    m = parse_mission("Run some tests")
    assert m.shards == 3 and m.gpu_type == "H100" and m.target == "packages/nodus/tests"
    assert m.self_heal is True and m.auto_fix is True
    assert "defaults" in str(m.derived)


def test_gpu_type_extraction():
    m = parse_mission("Deploy on A100 GPUs")
    assert m.gpu_type == "A100"
    assert any("gpu=A100" in d for d in m.derived)


def test_shard_count_from_across():
    m = parse_mission("Shard across 5 nodes")
    assert m.shards == 5
    assert "5 shards" in m.derived[0]


def test_shard_count_from_x_notation():
    m = parse_mission("Run on 4x H100")
    assert m.shards == 4 and m.gpu_type == "H100"


def test_shard_count_from_explicit_word():
    m = parse_mission("Use 7 shards for the job")
    assert m.shards == 7


def test_shard_count_clamped():
    m = parse_mission("Run on 999 replicas")  # over limit
    assert m.shards == 3  # unchanged, defaults


def test_target_path_extraction():
    m = parse_mission("Run `./tests/integration` suite")
    assert m.target == "./tests/integration"
    assert "target=" in m.derived[0]


def test_target_with_in():
    m = parse_mission("Execute tests in tests/gpu")
    assert m.target == "tests/gpu"


def test_artifact_collection():
    m = parse_mission("Gather report.xml and results.json at the end")
    assert set(m.collect) == {"report.xml", "results.json"}
    assert "collect=" in m.derived[0]


def test_self_heal_keyword():
    m = parse_mission("Auto-migrate if a node throttles")
    assert m.self_heal is True
    assert any("self-heal=on" in d for d in m.derived)


def test_self_heal_french():
    m = parse_mission("L'engine s'auto-migre si la température dépasse 80C")
    assert m.self_heal is True


def test_no_fix_request():
    m = parse_mission("Run tests but don't fix failures, just report")
    assert m.auto_fix is False
    assert any("auto-fix=off" in d for d in m.derived)


def test_scenario_dict():
    m = parse_mission("Run in ./tests/smoke across 2 A100s")
    s = m.scenario()
    assert s["shards"] == 2 and s["gpu_type"] == "A100" and s["target"] == "./tests/smoke"
    assert s["name"] == "mission"


def test_full_complex_mission():
    mission_text = """
    Run the full pytest suite in ./tests/integration across 4 H100s.
    Auto-heal if throttling happens. Collect report.xml and metrics.json.
    """
    m = parse_mission(mission_text)
    assert m.shards == 4
    assert m.gpu_type == "H100"
    assert m.target == "./tests/integration"
    assert set(m.collect) == {"report.xml", "metrics.json"}
    assert m.self_heal is True
    assert len(m.derived) >= 4
