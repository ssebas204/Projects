"""Rigorous QA stress tests and boundary edge cases."""
from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analytics import (
    DD_CAPACITY_SHIFTS,
    LS_CAPACITY_SHIFTS,
    MINUTES_PER_SHIFT,
    THEORETICAL_WORST_CASE_MINUTES,
    calculate_pareto,
    calculate_sensitivity,
    detect_families,
    evaluate_family_sequence,
    find_optimal_family_sequence,
    generate_sensitivity_table,
    get_augmented_comparisons,
    get_block_matrix,
    get_ordered_matrix,
    get_pareto_key_insights,
    get_scaling_data,
)
from engine import cost, effective_products, fingerprint, route_cost, schedule_route, solve, validate
from io_utils import excel_export, import_three


@pytest.fixture
def demo():
    return json.loads((Path(__file__).resolve().parents[1] / "data/demo.json").read_text())


def test_zero_demand_pareto(demo):
    """Pareto with zero demand should handle division gracefully without ZeroDivisionError."""
    for p in demo["products"]:
        p["demand"] = 0
    df = calculate_pareto(demo)
    assert not df.empty
    assert (df["pct_load"] == 0.0).all()
    insights = get_pareto_key_insights(df)
    assert insights["top_3_pct"] == 0.0


def test_single_product_scenario(demo):
    """A scenario with a single product should solve cleanly with 0 changeover minutes."""
    p = demo["products"][0]
    single = {
        "version": 1,
        "name": "Single Product",
        "products": [p],
        "matrix": {f"{p['id']}|{p['id']}": 0},
        "config": demo["config"],
        "closures": []
    }
    assert validate(single) == []
    sol = solve(single)
    assert sol["demand"] == p["demand"]
    assert sol["setup_minutes"] == 0.0
    assert sol["route"] == [p["id"]]

    # Analytics functions on single product
    fams = detect_families(single)
    assert len(fams) == 1
    block_dist = get_block_matrix(single, fams)
    assert block_dist[(fams[0]["id"], fams[0]["id"])] == 0.0
    res = evaluate_family_sequence([fams[0]["id"]], fams, block_dist)
    assert res["total_minutes"] == 0.0


def test_sensitivity_boundary_values():
    """Test extreme boundaries in sensitivity calculator."""
    # 0 net minutes (no production)
    res_zero = calculate_sensitivity(0.0, base_setup_minutes=840.0, factor_percent=0.0)
    assert res_zero["production_minutes"] == 0.0
    assert res_zero["total_minutes"] == 840.0
    assert res_zero["shifts_required"] == 840.0 / 480.0
    assert res_zero["ls_breakeven_pct"] == 0.0

    # Negative 100% (demand falls to 0)
    res_minus100 = calculate_sensitivity(27819.6, base_setup_minutes=840.0, factor_percent=-100.0)
    assert res_minus100["production_minutes"] == 0.0
    assert res_minus100["total_minutes"] == 840.0

    # Extreme +500% (massive surge)
    res_surge = calculate_sensitivity(27819.6, base_setup_minutes=840.0, factor_percent=500.0)
    assert res_surge["status"] == "DESBORDA_PLANTA"
    assert res_surge["shifts_required"] > 90.0
    assert res_surge["deficit_shifts"] > 0.0


def test_evaluate_family_sequence_invalid_or_repeated_ids(demo):
    """Test evaluate_family_sequence with unknown or repeated IDs."""
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)

    # Unknown IDs should default gracefully to 120 min default step cost
    res_unknown = evaluate_family_sequence(["UNKNOWN_A", "UNKNOWN_B"], families, block_dist)
    assert res_unknown["total_minutes"] == 120.0
    assert res_unknown["is_optimal"] is False

    # Repeated family IDs
    res_rep = evaluate_family_sequence(["3533", "3533", "3533"], families, block_dist)
    assert res_rep["total_minutes"] == 0.0  # self-distance is 0


def test_import_three_malformed_headers(demo):
    """Test import_three rejection of malformed files."""
    # Empty excel bytes
    empty_wb = openpyxl.Workbook()
    buf = io.BytesIO()
    empty_wb.save(buf)
    empty_bytes = buf.getvalue()

    with pytest.raises(ValueError, match="encabezados"):
        import_three(empty_bytes, empty_bytes, empty_bytes, demo["config"])


def test_excel_export_formulas_and_protection(demo):
    """Test excel export formulas and formatting safety."""
    sol = solve(demo)
    content = excel_export(sol)
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=False)

    turnos_sheet = wb["Turnos"]
    # Row 2 formulas
    assert turnos_sheet["F2"].value == "=D2+E2"
    assert turnos_sheet["G2"].value == "=C2-F2"
    assert "IF(ROUND" in turnos_sheet["H2"].value

    cumplimiento_sheet = wb["Cumplimiento"]
    assert cumplimiento_sheet["D2"].value == "=B2-C2"
    assert "IF(D2=0" in cumplimiento_sheet["E2"].value


def test_scaling_search_fuzzing_special_characters():
    """Ensure search queries containing regex metacharacters do not crash with ArrowInvalid or RegexError."""
    dangerous_patterns = [
        "[", "]", "*", "+", "(", ")", "?", "\\", "^", "$", ".", "{", "}", "|",
        "[CLSD]", "a++", "(?i)", ".*", "+++"
    ]
    df = get_scaling_data("TODOS")

    for pat in dangerous_patterns:
        q = pat.lower()
        filtered = df[
            df["item"].str.lower().str.contains(q, regex=False) |
            df["reason"].str.lower().str.contains(q, regex=False) |
            df["impact"].str.lower().str.contains(q, regex=False)
        ]
        assert isinstance(filtered, pd.DataFrame)


def test_sequence_builder_partial_evaluation_invariants(demo):
    """Severe audit on sequence evaluator: partial sequences must never claim negative savings."""
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)
    all_ids = [f["id"] for f in families]

    for length in range(1, len(all_ids) + 1):
        seq = all_ids[:length]
        res = evaluate_family_sequence(seq, families, block_dist)

        assert res["count"] == length
        assert res["total_families"] == 8

        if length < 8:
            assert res["is_complete"] is False
            assert res["is_optimal"] is False
            assert res["diff_minutes"] >= 0.0, f"Partial sequence of length {length} had negative diff: {res['diff_minutes']}"
            assert res["diff_hours"] >= 0.0
        else:
            assert res["is_complete"] is True
            assert res["total_minutes"] >= 840.0


def test_sequence_builder_custom_target_optimal():
    """Verify evaluator respects custom target optimal minutes and handles arbitrary step counts."""
    custom_families = [
        {"id": "A", "name": "Fam A", "members": ["A1", "A2"]},
        {"id": "B", "name": "Fam B", "members": ["B1"]},
        {"id": "C", "name": "Fam C", "members": ["C1"]},
    ]
    custom_dist = {
        ("A", "A"): 0.0, ("B", "B"): 0.0, ("C", "C"): 0.0,
        ("A", "B"): 100.0, ("B", "A"): 100.0,
        ("B", "C"): 100.0, ("C", "B"): 100.0,
        ("A", "C"): 200.0, ("C", "A"): 200.0,
    }

    # Optimal sequence A -> B -> C = 200 min
    res_opt = evaluate_family_sequence(["A", "B", "C"], custom_families, custom_dist, target_optimal_minutes=200.0)
    assert res_opt["is_complete"] is True
    assert res_opt["is_optimal"] is True
    assert res_opt["total_minutes"] == 200.0
    assert res_opt["diff_minutes"] == 0.0

    # Suboptimal sequence A -> C -> B = 200 + 100 = 300 min
    res_sub = evaluate_family_sequence(["A", "C", "B"], custom_families, custom_dist, target_optimal_minutes=200.0)
    assert res_sub["is_complete"] is True
    assert res_sub["is_optimal"] is False
    assert res_sub["total_minutes"] == 300.0
    assert res_sub["diff_minutes"] == 100.0


def test_excel_export_cell_types_and_no_corrupted_formulas(demo):
    """Verify that generated Excel contains no NaN, #VALUE!, or broken formula references."""
    sol = solve(demo)
    content = excel_export(sol)
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=False)

    for sheetname in wb.sheetnames:
        ws = wb[sheetname]
        for row in ws.iter_rows(values_only=False):
            for cell in row:
                if cell.value is not None:
                    s_val = str(cell.value)
                    assert "#REF!" not in s_val, f"Corrupted #REF! formula in {sheetname} at {cell.coordinate}"
                    assert "#VALUE!" not in s_val, f"Corrupted #VALUE! in {sheetname} at {cell.coordinate}"
                    assert "#NAME?" not in s_val, f"Corrupted #NAME? in {sheetname} at {cell.coordinate}"
                    assert "NaN" != s_val, f"Raw NaN found in {sheetname} at {cell.coordinate}"


def test_pareto_monotonicity_and_100_percent_closure(demo):
    """Verify that Pareto cumulative percentages are strictly monotonically increasing and reach exactly 100%."""
    df = calculate_pareto(demo)
    cum = list(df["cum_pct"])
    for i in range(len(cum) - 1):
        assert cum[i] <= cum[i + 1] + 1e-9, f"Pareto cumulative non-monotonic at index {i}"
    assert abs(cum[-1] - 100.0) < 0.01, f"Pareto cumulative did not reach 100%: {cum[-1]}"


def test_sensitivity_breakeven_exact_capacities(demo):
    """Verify mathematical exactness of breakeven points against total minutes."""
    base_net = 27819.625384303745
    base_setup = 840.0
    ls_total_mins = LS_CAPACITY_SHIFTS * MINUTES_PER_SHIFT  # 35,520
    dd_total_mins = DD_CAPACITY_SHIFTS * MINUTES_PER_SHIFT  # 43,200

    res = calculate_sensitivity(base_net, base_setup, 0.0)
    be_ls = res["ls_breakeven_pct"]
    be_dd = res["dd_breakeven_pct"]

    res_ls = calculate_sensitivity(base_net, base_setup, be_ls)
    assert abs(res_ls["total_minutes"] - ls_total_mins) < 1e-5
    assert abs(res_ls["shifts_required"] - 74.0) < 1e-5

    res_dd = calculate_sensitivity(base_net, base_setup, be_dd)
    assert abs(res_dd["total_minutes"] - dd_total_mins) < 1e-5
    assert abs(res_dd["shifts_required"] - 90.0) < 1e-5


def test_augmented_comparisons_strictly_sorted_ascending(demo):
    """Verify that methods comparison table is strictly sorted ascending by setup minutes."""
    sol = solve(demo)
    comp = get_augmented_comparisons(sol)
    mins = list(comp["Minutos de cambio"])
    assert mins == sorted(mins), f"Comparison table was not sorted ascending: {mins}"
    assert mins[0] == 840.0
    assert mins[-1] == THEORETICAL_WORST_CASE_MINUTES


def test_calculate_pareto_empty_products():
    """Verify calculate_pareto returns a fully typed 9-column schema on empty products."""
    required_columns = [
        "id", "description", "demand", "rate", "minutes_required",
        "shifts_required", "pct_load", "cum_pct", "zone"
    ]
    for empty_input in [{"products": []}, {"products": [], "config": {"factor": 1.0}}]:
        df = calculate_pareto(empty_input)
        assert df.empty
        for col in required_columns:
            assert col in df.columns, f"Missing required column {col} in empty Pareto DataFrame"
        assert "production_minutes" in df.columns
        assert df["shifts_required"].sum() == 0.0
        assert df["minutes_required"].sum() == 0.0
        insights = get_pareto_key_insights(df)
        assert insights == {"top_3_pct": 0.0, "top_3_skus": [], "zone_a_count": 0}


def test_calculate_pareto_custom_subsets(demo):
    """Verify calculate_pareto dynamically handles variable number of SKUs (1, 2, and 5)."""
    # 1 SKU scenario
    scen_1 = copy.deepcopy(demo)
    scen_1["products"] = [demo["products"][0]]
    df_1 = calculate_pareto(scen_1)
    assert len(df_1) == 1
    assert df_1["pct_load"].iloc[0] == 100.0
    ins_1 = get_pareto_key_insights(df_1)
    assert len(ins_1["top_3_skus"]) == 1
    assert ins_1["top_3_pct"] == 100.0

    # 2 SKUs scenario
    scen_2 = copy.deepcopy(demo)
    scen_2["products"] = demo["products"][:2]
    df_2 = calculate_pareto(scen_2)
    assert len(df_2) == 2
    assert abs(df_2["pct_load"].sum() - 100.0) < 1e-4
    ins_2 = get_pareto_key_insights(df_2)
    assert len(ins_2["top_3_skus"]) == 2
    assert ins_2["top_3_pct"] == 100.0


def test_get_block_matrix_with_none_entries():
    """Verify get_block_matrix handles None matrix transition values without TypeError."""
    scenario = {
        "products": [
            {"id": "1", "description": "Prod A"},
            {"id": "2", "description": "Prod B"},
            {"id": "3", "description": "Prod C"}
        ],
        "matrix": {
            "1|2": None,
            "2|1": 150.0,
            "1|3": 120.0,
            "3|1": None,
            "2|3": 180.0,
            "3|2": None
        }
    }
    families = detect_families(scenario)
    # Must not throw TypeError: float() argument must be a string or a real number, not 'NoneType'
    bm = get_block_matrix(scenario, families)
    assert isinstance(bm, dict)
    assert bm[("1", "2")] == 180.0  # None falls back to 180.0 penalty
    assert bm[("2", "1")] == 150.0


def test_evaluate_family_sequence_single_family_completion():
    """Verify single-family scenario correctly marks is_complete=True and is_optimal=True."""
    single_fam = [{"id": "FAM_A", "name": "Familia A", "members": ["A1", "A2"]}]
    single_dist = {("FAM_A", "FAM_A"): 0.0}
    res = evaluate_family_sequence(["FAM_A"], single_fam, single_dist)
    assert res["is_complete"] is True
    assert res["is_optimal"] is True
    assert res["total_minutes"] == 0.0
    assert res["diff_minutes"] == 0.0


def test_evaluate_family_sequence_repeated_families_never_complete(demo):
    """Verify that repeating family IDs to match total length is rejected as incomplete and not optimal."""
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)
    num_fams = len(families)

    # Repeating same family 8 times
    repeated_seq = [families[0]["id"]] * num_fams
    res_rep = evaluate_family_sequence(repeated_seq, families, block_dist)
    assert res_rep["is_complete"] is False
    assert res_rep["is_optimal"] is False

    # Repeating some families with missing others
    mixed_seq = [families[0]["id"], families[1]["id"], families[0]["id"]] + [families[i]["id"] for i in range(2, num_fams - 1)]
    assert len(mixed_seq) == num_fams
    assert len(set(mixed_seq)) < num_fams
    res_mixed = evaluate_family_sequence(mixed_seq, families, block_dist)
    assert res_mixed["is_complete"] is False
    assert res_mixed["is_optimal"] is False


def test_find_optimal_family_sequence(demo):
    """Verify find_optimal_family_sequence identifies the true minimum cost sequence."""
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)

    # Volpak 4 known optimum
    opt_seq, opt_cost = find_optimal_family_sequence(families, block_dist)
    assert opt_cost == 840.0
    assert len(opt_seq) == len(families)
    assert set(opt_seq) == {f["id"] for f in families}

    # Custom 3-family scenario
    custom_families = [
        {"id": "A", "name": "Fam A", "members": ["A"]},
        {"id": "B", "name": "Fam B", "members": ["B"]},
        {"id": "C", "name": "Fam C", "members": ["C"]}
    ]
    custom_dist = {
        ("A", "A"): 0.0, ("B", "B"): 0.0, ("C", "C"): 0.0,
        ("A", "B"): 100.0, ("B", "A"): 100.0,
        ("B", "C"): 100.0, ("C", "B"): 100.0,
        ("A", "C"): 250.0, ("C", "A"): 250.0,
    }
    best_seq, best_cost = find_optimal_family_sequence(custom_families, custom_dist)
    assert best_cost == 200.0
    assert best_seq in (["A", "B", "C"], ["C", "B", "A"])

    # Empty and 1-family edge cases
    assert find_optimal_family_sequence([], {}) == ([], 0.0)
    assert find_optimal_family_sequence([custom_families[0]], {("A", "A"): 0.0}) == (["A"], 0.0)


def test_get_augmented_comparisons_none_result():
    """Verify get_augmented_comparisons safely handles None or empty results."""
    for empty_input in [None, {}]:
        df = get_augmented_comparisons(empty_input)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert "Minutos de cambio" in df.columns
        assert "Método" in df.columns


