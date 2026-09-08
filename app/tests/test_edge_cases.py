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
