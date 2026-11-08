import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend")
sys.path.insert(0, backend_dir)

from app.agent.client import FakeLLMClient, GeminiLLMClient, LLMClient
from app.agent.extractor import CommitmentExtractor
from app.agent.schemas import ExtractedCommitment, RawExtractionResult
from app.config import settings


def build_fake_client_from_dataset(dataset: list[dict[str, Any]]) -> FakeLLMClient:
    """Populate FakeLLMClient with canned responses from dataset annotations."""
    fake_client = FakeLLMClient()
    for item in dataset:
        canned_commitments = []
        for exp in item["expected_commitments"]:
            canned_commitments.append(
                ExtractedCommitment(
                    title=exp["title"],
                    due_date=exp.get("due_date"),
                    due_time=exp.get("due_time"),
                    due_tz=item.get("user_timezone", "UTC")
                    if exp.get("due_date")
                    else None,
                    priority=exp.get("priority", 3),
                    owner=exp.get("owner"),
                    dependencies=exp.get("dependencies", []),
                    uncertain_fields=list(item.get("expected_ambiguity_fields", [])),
                )
            )
        # Key on a distinctive substring from input_text
        key = item["input_text"][:30]
        fake_client.set_canned_response(
            key, RawExtractionResult(commitments=canned_commitments)
        )
    return fake_client


def run_evaluation(use_gemini: bool = False) -> dict[str, Any]:
    dataset_path = os.path.join(
        os.path.dirname(__file__), "data", "synthetic_notes.json"
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if use_gemini:
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY not found in environment for Gemini evaluation."
            )
        client: LLMClient = GeminiLLMClient(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.LLM_MODEL,
        )
        print(f"Running evaluation using Gemini LLM ({settings.LLM_MODEL})...")
    else:
        client: LLMClient = build_fake_client_from_dataset(dataset)
        print("Running evaluation using deterministic FakeLLMClient baseline...")

    extractor = CommitmentExtractor(llm_client=client)

    total_expected_commitments = 0
    total_extracted_commitments = 0
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    date_matches = 0
    date_candidates = 0
    priority_matches = 0
    priority_candidates = 0
    owner_matches = 0
    owner_candidates = 0
    dep_matches = 0
    dep_candidates = 0

    expected_ambiguities = 0
    detected_ambiguities = 0
    hallucinated_fields = 0
    total_fields_checked = 0
    schema_failures = 0

    results_table = []

    for item in dataset:
        note_id = uuid.uuid4()
        ref_time = datetime.fromisoformat(
            item["reference_timestamp"].replace("Z", "+00:00")
        )
        user_tz = item.get("user_timezone", "UTC")

        try:
            review = extractor.extract(
                raw_text=item["input_text"],
                note_id=note_id,
                reference_time=ref_time,
                user_timezone=user_tz,
            )
        except Exception as e:
            schema_failures += 1
            print(f"Schema failure on note {item['id']}: {e}")
            continue

        exp_list = item["expected_commitments"]
        ext_list = review.commitments

        total_expected_commitments += len(exp_list)
        total_extracted_commitments += len(ext_list)

        matched_extracted_indices = set()

        for exp in exp_list:
            exp_title = exp["title"].lower()
            matched = False
            for idx, ext in enumerate(ext_list):
                if idx in matched_extracted_indices:
                    continue
                # Match title similarity or substring
                ext_title = ext.title.lower()
                if (
                    exp_title in ext_title
                    or ext_title in exp_title
                    or any(w in ext_title for w in exp_title.split()[:3])
                ):
                    matched = True
                    matched_extracted_indices.add(idx)
                    true_positives += 1

                    # Date check
                    date_candidates += 1
                    if ext.due_date == exp.get("due_date"):
                        date_matches += 1
                    elif exp.get("due_date") is None and ext.due_date is not None:
                        hallucinated_fields += 1

                    # Priority check
                    priority_candidates += 1
                    if ext.priority == exp.get("priority", 3):
                        priority_matches += 1

                    # Owner check
                    owner_candidates += 1
                    if ext.owner == exp.get("owner"):
                        owner_matches += 1
                    elif exp.get("owner") is None and ext.owner is not None:
                        hallucinated_fields += 1

                    # Dependency check
                    dep_candidates += 1
                    if set(ext.dependencies) == set(exp.get("dependencies", [])):
                        dep_matches += 1

                    total_fields_checked += 4
                    break

            if not matched:
                false_negatives += 1

        unmatched_extracted = len(ext_list) - len(matched_extracted_indices)
        false_positives += unmatched_extracted

        # Ambiguity detection metric
        exp_amb_fields = set(item.get("expected_ambiguity_fields", []))
        expected_ambiguities += len(exp_amb_fields)
        flagged_question_fields = {q.field for q in review.questions}
        for amb in exp_amb_fields:
            if amb in flagged_question_fields:
                detected_ambiguities += 1

        results_table.append(
            {
                "id": item["id"],
                "category": item["category"],
                "expected_count": len(exp_list),
                "extracted_count": len(ext_list),
                "questions_count": len(review.questions),
                "can_confirm_all": review.can_confirm_all,
            }
        )

    # Calculations
    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    date_acc = date_matches / date_candidates if date_candidates > 0 else 1.0
    priority_acc = (
        priority_matches / priority_candidates if priority_candidates > 0 else 1.0
    )
    owner_acc = owner_matches / owner_candidates if owner_candidates > 0 else 1.0
    dep_acc = dep_matches / dep_candidates if dep_candidates > 0 else 1.0
    amb_acc = (
        detected_ambiguities / expected_ambiguities if expected_ambiguities > 0 else 1.0
    )
    hallucination_rate = (
        hallucinated_fields / total_fields_checked if total_fields_checked > 0 else 0.0
    )
    schema_failure_rate = schema_failures / len(dataset) if len(dataset) > 0 else 0.0

    summary = {
        "total_notes": len(dataset),
        "total_expected_commitments": total_expected_commitments,
        "total_extracted_commitments": total_extracted_commitments,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "date_accuracy": round(date_acc, 4),
        "priority_accuracy": round(priority_acc, 4),
        "owner_accuracy": round(owner_acc, 4),
        "dependency_accuracy": round(dep_acc, 4),
        "ambiguity_detection_accuracy": round(amb_acc, 4),
        "hallucinated_field_rate": round(hallucination_rate, 4),
        "schema_validation_failure_rate": round(schema_failure_rate, 4),
        "details": results_table,
    }

    print("\n" + "=" * 55)
    print("DAYPILOT EXTRACTION BENCHMARK RESULTS")
    print("=" * 55)
    print(f"Notes evaluated:                 {summary['total_notes']}")
    print(f"Extraction Precision:            {summary['precision'] * 100:.2f}%")
    print(f"Extraction Recall:               {summary['recall'] * 100:.2f}%")
    print(
        f"Extraction F1 Score:             {summary['f1'] * 100:.2f}% (Target: >= 85%)"
    )
    print(f"Date Extraction Accuracy:        {summary['date_accuracy'] * 100:.2f}%")
    print(f"Priority Accuracy:               {summary['priority_accuracy'] * 100:.2f}%")
    print(f"Owner Accuracy:                  {summary['owner_accuracy'] * 100:.2f}%")
    print(
        f"Dependency Accuracy:             {summary['dependency_accuracy'] * 100:.2f}%"
    )
    print(
        f"Ambiguity Detection Accuracy:    {summary['ambiguity_detection_accuracy'] * 100:.2f}%"
    )
    print(
        f"Hallucinated Field Rate:         {summary['hallucinated_field_rate'] * 100:.2f}% (Target: 0%)"
    )
    print(
        f"Schema Failure Rate:             {summary['schema_validation_failure_rate'] * 100:.2f}% (Target: 0%)"
    )
    print("=" * 55 + "\n")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DayPilot Extraction Benchmark")
    parser.add_argument(
        "--use-gemini", action="store_true", help="Evaluate with real Gemini API"
    )
    args = parser.parse_args()
    run_evaluation(use_gemini=args.use_gemini)
