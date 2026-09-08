"""Rigorous QA tests for analytics, sensitivity, family detection, and scaling logic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analytics import (
    DEFAULT_FAMILY_NAMES,
    DEFAULT_MATURITY_RESPONSES,
    LS_CAPACITY_SHIFTS,
    DD_CAPACITY_SHIFTS,
    THEORETICAL_WORST_CASE_MINUTES,
    calculate_maturity_score,
    calculate_pareto,
    calculate_sensitivity,
    detect_families,
    evaluate_family_sequence,
    generate_sensitivity_table,
    get_augmented_comparisons,
    get_block_matrix,
    get_ordered_matrix,
    get_pareto_key_insights,
    get_scaling_data,
)
from engine import solve


@pytest.fixture
def demo():
    return json.loads((Path(__file__).resolve().parents[1] / "data/demo.json").read_text())


def test_detect_families_volpak4(demo):
    families = detect_families(demo)
    assert len(families) == 8, f"Expected 8 families, found {len(families)}"

    # Check that representative IDs match the 8 known blocks
    rep_ids = {f["id"] for f in families}
    # Every product in demo must belong to exactly one family
    all_members = []
    for f in families:
        all_members.extend(f["members"])
    assert len(all_members) == 17
    assert len(set(all_members)) == 17

    # Verify key family clusters
    fam_of = {}
    for f in families:
        for m in f["members"]:
            fam_of[m] = f["name"]

    # Mayonesas/Emulsiones cluster
    assert fam_of["3278"] == fam_of["16816"] == fam_of["17246"] == fam_of["3749"]
    # Tomates cluster
    assert fam_of["5998"] == fam_of["15881"] == fam_of["16787"]
    # Mostazas cluster
    assert fam_of["3757"] == fam_of["3925"] == fam_of["6616"]


def test_block_matrix_and_optimal_sequence(demo):
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)

    # Diagonal must be 0
    for f in families:
        assert block_dist[(f["id"], f["id"])] == 0.0

    # Off-diagonal must be at least 120
    for f1 in families:
        for f2 in families:
            if f1["id"] != f2["id"]:
                assert block_dist[(f1["id"], f2["id"])] >= 120.0

    # Test known optimal family order from Sheet 06
    # 3533 (S5) -> 3643 (S4) -> 15564 (S3) -> 5998 (F3) -> 6743 (S2) -> 6639 (S1) -> 3278 (F2) -> 3757 (F1)
    optimal_family_order = ["3533", "3643", "15564", "5998", "6743", "6639", "3278", "3757"]
    res = evaluate_family_sequence(optimal_family_order, families, block_dist)
    assert res["is_optimal"] is True
    assert res["total_minutes"] == 840.0
    assert res["diff_minutes"] == 0.0
    assert len(res["transitions"]) == 7
    assert all(t["cost_minutes"] == 120.0 for t in res["transitions"])

    # Test an order with known 180 min jump (e.g. Mostaza -> Barbecue)
    suboptimal_order = ["3757", "6639", "3278", "6743", "5998", "15564", "3643", "3533"]
    sub_res = evaluate_family_sequence(suboptimal_order, families, block_dist)
    assert sub_res["total_minutes"] > 840.0
    assert sub_res["is_optimal"] is False
    assert sub_res["diff_minutes"] > 0.0


def test_evaluate_sequence_edge_cases(demo):
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)

    # Empty
    empty_res = evaluate_family_sequence([], families, block_dist)
    assert empty_res["total_minutes"] == 0.0
    assert empty_res["is_optimal"] is False

    # Single family
    single_res = evaluate_family_sequence(["3533"], families, block_dist)
    assert single_res["total_minutes"] == 0.0
    assert single_res["is_optimal"] is False

    # Incomplete sequence (3 families)
    partial_res = evaluate_family_sequence(["3533", "3643", "15564"], families, block_dist)
    assert partial_res["total_minutes"] == 240.0
    assert partial_res["is_complete"] is False
    assert partial_res["is_optimal"] is False


def test_pareto_concentration_volpak4(demo):
    df = calculate_pareto(demo)
    assert len(df) == 17
    assert df["production_minutes"].sum() > 27800.0

    insights = get_pareto_key_insights(df)
    # 3 SKUs (16816 Mayonesa ZEV, 5998 Tomate ZEV, 17246 Mayonesa LINE) must concentrate ~62.2%
    top_3_ids = list(df.head(3)["id"])
    assert set(top_3_ids) == {"16816", "5998", "17246"}
    assert 62.0 <= insights["top_3_pct"] <= 62.5
    assert (df["zone"] == "A").sum() >= 3


def test_sensitivity_breakeven_points(demo):
    base_net_minutes = 27819.625384303745
    base_setup = 840.0

    # Base case (0%)
    base = calculate_sensitivity(base_net_minutes, base_setup, 0.0)
    assert round(base["production_minutes"], 1) == 27819.6
    assert round(base["total_minutes"], 1) == 28659.6
    assert round(base["shifts_required"], 2) == 59.71
    assert base["status"] == "CABEN_EN_LS"
    assert round(base["slack_ls_shifts"], 2) == round(74 - 59.71, 2)
    assert round(base["ls_breakeven_pct"], 1) == 24.7
    assert round(base["dd_breakeven_pct"], 1) == 52.3

    # Exact L-S breakeven (+24.66%)
    be_ls = calculate_sensitivity(base_net_minutes, base_setup, base["ls_breakeven_pct"])
    assert abs(be_ls["shifts_required"] - 74.0) < 0.01

    # Exact D-D breakeven (+52.27%)
    be_dd = calculate_sensitivity(base_net_minutes, base_setup, base["dd_breakeven_pct"])
    assert abs(be_dd["shifts_required"] - 90.0) < 0.01

    # Over L-S but within D-D (+30%)
    over_ls = calculate_sensitivity(base_net_minutes, base_setup, 30.0)
    assert over_ls["status"] == "REQUIERE_DD"
    assert over_ls["shifts_required"] > 74.0
    assert over_ls["shifts_required"] <= 90.0

    # Critical overflow (+60%)
    crit = calculate_sensitivity(base_net_minutes, base_setup, 60.0)
    assert crit["status"] == "DESBORDA_PLANTA"
    assert crit["shifts_required"] > 90.0
    assert crit["deficit_shifts"] > 0.0

    # Sensitivity table generation
    table = generate_sensitivity_table(base_net_minutes, base_setup)
    assert not table.empty
    assert len(table) == 11


def test_ordered_matrix(demo):
    df_fam, ids_fam, labels_fam = get_ordered_matrix(demo, order_by="family")
    assert df_fam.shape == (17, 17)
    assert len(ids_fam) == 17

    df_code, ids_code, labels_code = get_ordered_matrix(demo, order_by="code")
    assert df_code.shape == (17, 17)
    # Check that code order is strictly sorted numerically
    int_ids = [int(x) for x in ids_code]
    assert int_ids == sorted(int_ids)


def test_augmented_comparisons(demo):
    sol = solve(demo)
    comp_df = get_augmented_comparisons(sol)
    assert len(comp_df) == 5
    methods = list(comp_df["Método"])
    assert "Óptimo demostrado (TSP exacto)" in methods[0]
    assert any("Peor caso teórico" in m for m in methods)

    worst_row = comp_df[comp_df["Método"].str.contains("Peor caso")].iloc[0]
    assert worst_row["Minutos de cambio"] == THEORETICAL_WORST_CASE_MINUTES
    assert worst_row["Horas de cambio"] == 48.0
    assert worst_row["Diferencia Horas"] == 34.0


def test_scaling_data_filters():
    all_data = get_scaling_data("TODOS")
    assert len(all_data) == 14

    bloqueantes = get_scaling_data("BLOQUEANTE")
    assert len(bloqueantes) == 4
    assert all(r["criticality"] == "BLOQUEANTE" for _, r in bloqueantes.iterrows())

    altos = get_scaling_data("ALTO IMPACTO")
    assert len(altos) == 5

    refinamientos = get_scaling_data("REFINAMIENTO")
    assert len(refinamientos) == 5


def test_calculate_maturity_score_defaults():
    mat = calculate_maturity_score()
    assert 55.0 <= mat["score_pct"] <= 75.0
    assert mat["count_si"] >= 4
    assert mat["count_proceso"] >= 5
    assert mat["total_items"] == 14
    assert "Operativo" in mat["level"]


def test_calculate_maturity_score_all_si():
    all_si = {i: "✅ Sí (Disponible)" for i in range(1, 15)}
    mat = calculate_maturity_score(all_si)
    assert mat["score_pct"] == 100.0
    assert mat["count_si"] == 14
    assert mat["count_proceso"] == 0
    assert mat["count_no"] == 0
    assert len(mat["blocking_missing"]) == 0
    assert "Avanzado" in mat["level"]


def test_calculate_maturity_score_all_no():
    all_no = {i: "❌ No disponible" for i in range(1, 15)}
    mat = calculate_maturity_score(all_no)
    assert mat["score_pct"] == 0.0
    assert mat["count_no"] == 14
    assert len(mat["blocking_missing"]) == 4
    assert "Diagnóstico" in mat["level"]


def test_calculate_maturity_score_missing_blocking():
    custom = {i: "SI" for i in range(1, 15)}
    custom[1] = "NO_DISPONIBLE"  # Bloqueante 1 missing
    mat = calculate_maturity_score(custom)
    assert len(mat["blocking_missing"]) == 1
    assert "Asignación producto" in mat["blocking_missing"][0]
    assert mat["score_pct"] < 100.0

