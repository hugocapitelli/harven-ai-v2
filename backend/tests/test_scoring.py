"""DATA-GAM-3 — unit tests for the pure ``compute_performance_score`` function.

Pure-function coverage: insufficient signal -> ``None``; clamp at both ends;
per-turn evaluation aggregation; engagement fallback determinism; input is never
mutated.
"""
from services.scoring import compute_performance_score


def _user(content, **meta):
    turn = {"role": "user", "content": content}
    if meta:
        turn["metadata"] = meta
    return turn


def _tutor(content="Boa. E por quê?"):
    return {"role": "assistant", "content": content, "agent_type": "socrates"}


# ── insufficient signal -> None ─────────────────────────────────────────
def test_none_when_no_turns():
    assert compute_performance_score(None) is None
    assert compute_performance_score([]) is None


def test_none_when_no_student_turns():
    # Only tutor turns — nothing the student did to score.
    turns = [_tutor(), _tutor()]
    assert compute_performance_score(turns) is None


def test_none_when_student_turns_all_empty():
    # Student "spoke" but with no real content -> not scorable, not a forced 0.
    turns = [_user(""), _user("   "), _tutor()]
    assert compute_performance_score(turns) is None


# ── per-turn evaluation signal (preferred path) ─────────────────────────
def test_perfect_evaluation_scores_100():
    turns = [
        _user("resposta completa e correta", is_correct=True),
        _tutor(),
        _user("outra resposta correta", is_correct=True),
    ]
    assert compute_performance_score(turns) == 100


def test_all_wrong_evaluation_scores_0_not_none():
    # Evaluated but all incorrect -> a real, honest 0 (signal exists), not None.
    turns = [
        _user("resposta errada", is_correct=False),
        _user("outra errada", is_correct=False),
    ]
    assert compute_performance_score(turns) == 0


def test_mixed_correctness_averages():
    turns = [
        _user("certa", is_correct=True),
        _user("errada", is_correct=False),
    ]
    # mean(1.0, 0.0) * 100 = 50
    assert compute_performance_score(turns) == 50


def test_numeric_fraction_score():
    turns = [_user("resposta", score=0.8), _user("resposta", score=0.6)]
    # mean(0.8, 0.6) * 100 = 70
    assert compute_performance_score(turns) == 70


def test_numeric_percentage_score_normalised():
    turns = [_user("resposta", score=90), _user("resposta", score=70)]
    # 90 and 70 treated as percentages -> mean 80
    assert compute_performance_score(turns) == 80


def test_verdict_labels():
    turns = [
        _user("a", verdict="APPROVED"),
        _user("b", verdict="NEEDS_REVISION"),
        _user("c", verdict="REJECTED"),
    ]
    # mean(1.0, 0.5, 0.0) * 100 = 50
    assert compute_performance_score(turns) == 50


def test_out_of_range_numeric_falls_through_to_correctness():
    # score is garbage (out of range) but is_correct present -> correctness wins.
    turns = [_user("resposta", score=999, is_correct=True)]
    assert compute_performance_score(turns) == 100


# ── clamp guarantees ────────────────────────────────────────────────────
def test_score_always_within_bounds_evaluation():
    turns = [_user("resposta", score=1.0), _user("resposta", score=1.0)]
    result = compute_performance_score(turns)
    assert result is not None and 0 <= result <= 100


def test_score_always_within_bounds_fallback():
    # Deep, substantive dialogue with no per-turn eval -> still clamped <= 100.
    turns = [_user("resposta bem desenvolvida numero " + str(i)) for i in range(20)]
    result = compute_performance_score(turns)
    assert result is not None and 0 <= result <= 100
    assert result == 100  # saturates at the target depth ceiling


# ── engagement fallback (no per-turn evaluation) ────────────────────────
def test_fallback_single_trivial_turn_scores_low():
    # One short "ok" -> engaged but shallow: low but non-None (student did speak).
    turns = [_user("ok")]
    result = compute_performance_score(turns)
    # depth_fraction = 1/4 = 0.25, substance_fraction = 0 (too short)
    # 100 * (0.6*0.25 + 0.4*0) = 15
    assert result == 15


def test_fallback_full_substantive_dialogue_scores_high():
    turns = [
        _user("Primeira resposta desenvolvida com argumento."),
        _tutor(),
        _user("Segunda resposta aprofundando o raciocinio."),
        _tutor(),
        _user("Terceira resposta conectando os conceitos."),
        _tutor(),
        _user("Quarta resposta concluindo a discussao."),
    ]
    # depth 4 -> depth_fraction 1.0; all substantive -> substance 1.0 -> 100
    assert compute_performance_score(turns) == 100


def test_fallback_is_deterministic():
    turns = [
        _user("Resposta substantiva um."),
        _user("Resposta substantiva dois."),
    ]
    first = compute_performance_score(turns)
    second = compute_performance_score(turns)
    assert first == second
    # depth 2 -> depth_fraction 0.5; substance 2/2 = 1.0
    # 100 * (0.6*0.5 + 0.4*1.0) = 70
    assert first == 70


# ── purity ──────────────────────────────────────────────────────────────
def test_does_not_mutate_input():
    turns = [_user("resposta", is_correct=True), _tutor()]
    snapshot = [dict(t) for t in turns]
    compute_performance_score(turns)
    assert turns == snapshot
