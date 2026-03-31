#!/usr/bin/env python3
"""
Unit tests for EPIC 5 guardrails:
1. PHI protection (execution-time blocking)
2. Healthcare logic validation (post-execution warning/critical)
"""

import sys
import time
from datetime import datetime, date
from app.db.sql_policy import enforce_sql_policy, BLOCKED_COLUMNS, SAFE_OUTPUT_COLUMNS
from app.db.query_executor import _validate_healthcare_rules


def test_phi_guardrails():
    """Test execution-time PHI blocking."""
    print("\n=== PHI GUARDRAILS TEST ===\n")
    
    test_cases = [
        {
            "name": "PASS: Safe aggregation by gender",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person GROUP BY gender",
            "should_pass": True,
            "reason": "Only safe dimensions (gender) and aggregation (COUNT)"
        },
        {
            "name": "PASS: Safe aggregation by stage",
            "sql": "SELECT stage, COUNT(*) as total FROM anchor_view.condition_occurrence GROUP BY stage",
            "should_pass": True,
            "reason": "Stage is in SAFE_OUTPUT_COLUMNS, COUNT is aggregate"
        },
        {
            "name": "BLOCK: SELECT * is prohibited",
            "sql": "SELECT * FROM anchor_view.person",
            "should_pass": False,
            "reason": "SELECT * is blocked by PHI policy"
        },
        {
            "name": "BLOCK: Accessing person_id",
            "sql": "SELECT person_id, gender FROM anchor_view.person",
            "should_pass": False,
            "reason": "person_id is in BLOCKED_COLUMNS"
        },
        {
            "name": "BLOCK: Accessing name directly",
            "sql": "SELECT name, age_group FROM anchor_view.person",
            "should_pass": False,
            "reason": "name is in BLOCKED_COLUMNS"
        },
        {
            "name": "BLOCK: Patient-level output (non-aggregated unsafe fields)",
            "sql": "SELECT year_of_birth, ethnicity FROM anchor_view.person LIMIT 10",
            "should_pass": False,
            "reason": "year_of_birth is not in SAFE_OUTPUT_COLUMNS and output is non-aggregated"
        },
        {
            "name": "PASS: Safe dimensions only",
            "sql": "SELECT gender, race, age_group FROM anchor_view.person LIMIT 100",
            "should_pass": True,
            "reason": "All fields (gender, race, age_group) are in SAFE_OUTPUT_COLUMNS"
        },
        {
            "name": "PASS: Aggregation with aliases",
            "sql": "SELECT gender, COUNT(DISTINCT person_id) as num_patients FROM anchor_view.person GROUP BY gender",
            "should_pass": True,
            "reason": "Aggregate function COUNT hides person_id, gender is safe"
        },
        {
            "name": "BLOCK: Free-text notes access",
            "sql": "SELECT free_text_notes FROM anchor_view.condition_occurrence",
            "should_pass": False,
            "reason": "free_text_notes is in BLOCKED_COLUMNS"
        },
        {
            "name": "PASS: Safe aggregation over multiple dimensions",
            "sql": "SELECT gender, age_group, COUNT(*) as patient_count, SUM(total) as total_value FROM anchor_view.condition_occurrence GROUP BY gender, age_group",
            "should_pass": True,
            "reason": "Gender and age_group are safe; aggregation used"
        },
        {
            "name": "PASS: Schema value whitelist (valid gender value)",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value = 'male' GROUP BY gender",
            "should_pass": True,
            "reason": "'male' is documented as an allowed value in schema"
        },
        {
            "name": "BLOCK: Schema value whitelist (invalid gender value)",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value = 'robot' GROUP BY gender",
            "should_pass": False,
            "reason": "'robot' is not in schema-allowed values"
        },
        {
            "name": "PASS: Schema value whitelist LIKE valid",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value LIKE '%male%' GROUP BY gender",
            "should_pass": True,
            "reason": "LIKE pattern matches schema-allowed value"
        },
        {
            "name": "BLOCK: Schema value whitelist LIKE invalid",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value LIKE '%robot%' GROUP BY gender",
            "should_pass": False,
            "reason": "LIKE pattern does not match schema-allowed values"
        },
        {
            "name": "PASS: Schema value whitelist NOT IN valid list",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value NOT IN ('male', 'female') GROUP BY gender",
            "should_pass": True,
            "reason": "All literals in NOT IN are schema-allowed values"
        },
        {
            "name": "BLOCK: Schema value whitelist NOT IN invalid list",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value NOT IN ('male', 'robot') GROUP BY gender",
            "should_pass": False,
            "reason": "One literal in NOT IN is outside schema-allowed values"
        },
        {
            "name": "PASS: Schema value whitelist <> valid literal",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value <> 'female' GROUP BY gender",
            "should_pass": True,
            "reason": "<> literal is schema-allowed"
        },
        {
            "name": "BLOCK: Schema value whitelist <> invalid literal",
            "sql": "SELECT gender, COUNT(*) as patient_count FROM anchor_view.person WHERE gender_source_value <> 'robot' GROUP BY gender",
            "should_pass": False,
            "reason": "<> literal is outside schema-allowed values"
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        try:
            safe_sql = enforce_sql_policy(
                tc["sql"],
                allowed_tables=["person", "death", "condition_occurrence", "procedure_occurrence", "drug_exposure_cancerdrugs", "measurement_mutation"],
                allowed_schema="anchor_view",
                hard_limit=5000,
            )
            if tc["should_pass"]:
                print(f"✓ {tc['name']}")
                print(f"  → {tc['reason']}")
                passed += 1
            else:
                print(f"✗ {tc['name']}")
                print(f"  ✗ EXPECTED TO BLOCK but passed: {tc['reason']}")
                failed += 1
        except ValueError as e:
            if not tc["should_pass"]:
                print(f"✓ {tc['name']}")
                print(f"  → Blocked: {str(e)[:80]}")
                passed += 1
            else:
                print(f"✗ {tc['name']}")
                print(f"  ✗ UNEXPECTED BLOCK: {str(e)}")
                failed += 1
        except Exception as e:
            print(f"✗ {tc['name']}")
            print(f"  ✗ Unexpected error: {type(e).__name__}: {str(e)[:80]}")
            failed += 1
    
    print(f"\n--- PHI Guardrails Summary ---")
    print(f"Passed: {passed}/{len(test_cases)}")
    print(f"Failed: {failed}/{len(test_cases)}")
    return failed == 0


def test_healthcare_validation():
    """Test post-execution healthcare logic validation."""
    print("\n=== HEALTHCARE LOGIC VALIDATION TEST ===\n")
    
    test_cases = [
        {
            "name": "PASS: Valid dates (birth < death)",
            "data": {
                "columns": ["person_id", "year_of_birth", "death_date"],
                "rows": [
                    {"person_id": 1, "year_of_birth": 1980, "death_date": "2020-05-15"},
                ],
            },
            "expect_critical": False,
        },
        {
            "name": "CRITICAL: Invalid dates (death <= birth)",
            "data": {
                "columns": ["person_id", "birth_date", "death_date"],
                "rows": [
                    {"person_id": 1, "birth_date": "2000-01-01", "death_date": "1990-05-15"},
                ],
            },
            "expect_critical": True,
        },
        {
            "name": "PASS: Valid staging",
            "data": {
                "columns": ["person_id", "stage"],
                "rows": [
                    {"person_id": 1, "stage": "II"},
                    {"person_id": 2, "stage": "IIIA"},
                    {"person_id": 3, "stage": "Unknown"},
                ],
            },
            "expect_critical": False,
        },
        {
            "name": "WARNING: Invalid staging",
            "data": {
                "columns": ["person_id", "stage"],
                "rows": [
                    {"person_id": 1, "stage": "VI"},
                    {"person_id": 2, "stage": "Invalid Stage"},
                ],
            },
            "expect_critical": False,  # Invalid stage is warning, not critical
            "expect_warning": True,
        },
        {
            "name": "CRITICAL: Negative count",
            "data": {
                "columns": ["gender", "patient_count"],
                "rows": [
                    {"gender": "M", "patient_count": -5},
                ],
            },
            "expect_critical": True,
        },
        {
            "name": "PASS: Non-negative counts",
            "data": {
                "columns": ["gender", "num_cases", "total_patients"],
                "rows": [
                    {"gender": "M", "num_cases": 100, "total_patients": 500},
                    {"gender": "F", "num_cases": 200, "total_patients": 600},
                ],
            },
            "expect_critical": False,
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        warnings, critical = _validate_healthcare_rules(tc["data"])
        
        has_critical = len(critical) > 0
        has_warning = len(warnings) > 0
        
        if tc["expect_critical"] and has_critical:
            print(f"✓ {tc['name']}")
            print(f"  → {critical[0] if critical else ''}")
            passed += 1
        elif not tc["expect_critical"] and not has_critical:
            if tc.get("expect_warning") and has_warning:
                print(f"✓ {tc['name']}")
                print(f"  → {warnings[0] if warnings else ''}")
                passed += 1
            elif not tc.get("expect_warning"):
                print(f"✓ {tc['name']}")
                print(f"  → No issues detected (as expected)")
                passed += 1
            else:
                print(f"✗ {tc['name']}")
                print(f"  ✗ Expected warning but got none")
                failed += 1
        else:
            print(f"✗ {tc['name']}")
            if tc["expect_critical"] and not has_critical:
                print(f"  ✗ Expected critical but got none. Warnings: {warnings}")
            else:
                print(f"  ✗ Unexpected critical: {critical}")
            failed += 1
    
    print(f"\n--- Healthcare Validation Summary ---")
    print(f"Passed: {passed}/{len(test_cases)}")
    print(f"Failed: {failed}/{len(test_cases)}")
    return failed == 0


if __name__ == "__main__":
    phi_ok = test_phi_guardrails()
    hc_ok = test_healthcare_validation()
    
    print(f"\n=== FINAL RESULT ===")
    if phi_ok and hc_ok:
        print("✓ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Some tests failed")
        sys.exit(1)
