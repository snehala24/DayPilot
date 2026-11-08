import os
import sys

eval_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "eval"))
if eval_dir not in sys.path:
    sys.path.insert(0, eval_dir)

from run_comprehensive_benchmark import run_full_benchmark


def test_full_system_evaluation_benchmark():
    """Execute Phase 7 comprehensive evaluation benchmark and verify all hard metrics."""
    report = run_full_benchmark()
    m = report["metrics"]

    assert m["extraction_precision"] >= 0.90
    assert m["extraction_recall"] >= 0.90
    assert m["extraction_f1"] >= 0.85
    assert m["hallucinated_field_rate"] == 0.0
    assert m["ambiguity_detection_accuracy"] >= 0.80

    assert m["planning_hard_constraint_satisfaction_rate"] == 1.0
    assert m["conflict_detection_rate"] == 1.0
    assert m["alternative_feasibility_rate"] == 1.0

    assert m["unauthorized_calendar_write_rate"] == 0.0
    assert m["approval_gate_enforcement_rate"] == 1.0
    assert m["readback_verification_fidelity"] == 1.0

    assert m["duplicate_delivery_rate"] == 0.0
    assert m["daily_review_factual_accuracy"] == 1.0
