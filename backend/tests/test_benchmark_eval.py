import os
import sys

# Ensure eval directory is in sys.path
eval_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "eval"))
if eval_dir not in sys.path:
    sys.path.insert(0, eval_dir)

from run_eval import run_evaluation


def test_synthetic_notes_benchmark_metrics():
    """Evaluate all 20 labeled synthetic notes and assert PRD quality targets."""
    summary = run_evaluation(use_gemini=False)

    assert summary["total_notes"] >= 20, (
        "Must evaluate at least 20 labeled synthetic notes"
    )
    assert summary["f1"] >= 0.85, f"F1 score {summary['f1']} is below target 0.85"
    assert summary["precision"] >= 0.90, (
        f"Precision {summary['precision']} is below 0.90"
    )
    assert summary["recall"] >= 0.90, f"Recall {summary['recall']} is below 0.90"
    assert summary["hallucinated_field_rate"] == 0.0, (
        "Hallucinated field rate must be 0"
    )
    assert summary["schema_validation_failure_rate"] == 0.0, (
        "Schema validation failure rate must be 0"
    )
    assert summary["ambiguity_detection_accuracy"] >= 0.80, (
        "Ambiguity detection accuracy must be >= 0.80"
    )
