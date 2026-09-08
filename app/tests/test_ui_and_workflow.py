"""Comprehensive QA test suite verifying all 7 features, UI components, workflows, and edge cases."""
from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import openpyxl
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analytics import (
    calculate_pareto,
    calculate_sensitivity,
    detect_families,
    evaluate_family_sequence,
    get_augmented_comparisons,
    get_block_matrix,
    get_ordered_matrix,
    get_scaling_data,
)
from engine import fingerprint, route_cost, schedule_route, solve, validate
from io_utils import excel_export, import_three


@pytest.fixture
def demo():
    return json.loads((Path(__file__).resolve().parents[1] / "data/demo.json").read_text())


# ---------------------------------------------------------------------------
# 1. STREAMLIT APP HEADLESS INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_app_clean_initialization():
    """Verify that the full Streamlit app initializes with 0 exceptions and renders tabs."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception, f"App threw uncaught exception on boot: {at.exception}"
    main_tab_labels = [t.label for t in at.tabs if any(s in t.label for s in ["Resumen", "Productos", "Calendario", "Plan", "Reta", "Simulador", "Métodos", "Escalamiento"])]
    assert len(main_tab_labels) == 8, f"Expected 8 main tabs, found {len(main_tab_labels)}"


def test_app_interactive_sensitivity_slider():
    """Verify that moving the sensitivity slider updates state without crashing."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Locate slider widget and adjust value to +30%
    sliders = at.slider
    sim_sliders = [s for s in sliders if "demanda" in s.label.lower() or "necesidad" in s.label.lower()]
    assert len(sim_sliders) >= 1
    sim_sliders[0].set_value(30).run()
    assert not at.exception


def test_app_interactive_matrix_toggle():
    """Verify that toggling between Por Familia and Por Código updates state cleanly."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    radios = at.radio
    matrix_radios = [r for r in radios if "matriz" in r.label.lower()]
    assert len(matrix_radios) >= 1
    matrix_radio = matrix_radios[0]
    
    # Toggle to Por Código
    code_opt = [o for o in matrix_radio.options if "Código" in o][0]
    matrix_radio.set_value(code_opt).run()
    assert not at.exception

    # Toggle to Por Familia
    fam_opt = [o for o in matrix_radio.options if "Familia" in o][0]
    matrix_radio.set_value(fam_opt).run()
    assert not at.exception


def test_app_game_interaction():
    """Verify interactive sequence builder button clicks and reset in the mini-game."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Find the '★ Cargar secuencia óptima (840 min)' button
    opt_btn = [b for b in at.button if "840 min" in b.label]
    assert len(opt_btn) == 1
    opt_btn[0].click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 8

    # Reset button
    reset_btn = [b for b in at.button if "Reiniciar" in b.label]
    assert len(reset_btn) >= 1
    reset_btn[0].click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 0


def test_app_scaling_roadmap_filter():
    """Verify that the scaling filter radio filters the scaling roadmap without crashing."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    radios = at.radio
    scale_radios = [r for r in radios if "criticidad" in r.label.lower()]
    assert len(scale_radios) >= 1
    scale_radio = scale_radios[0]
    for opt in ["BLOQUEANTE", "ALTO IMPACTO", "REFINAMIENTO", "TODOS"]:
        scale_radio.set_value(opt).run()
        assert not at.exception


# ---------------------------------------------------------------------------
# 2. FEATURE-BY-FEATURE STRICT NUMERICAL & INTEGRITY AUDITS
# ---------------------------------------------------------------------------

def test_feature1_executive_summary_exact_numbers(demo):
    """Audits Requirement 1: Executive summary & high impact KPIs."""
    sol = solve(demo)
    assert sol["demand"] == 86331
    assert sol["produced"] == 86331
    assert sol["setup_minutes"] == 840.0
    assert sol["optimization"]["status"] == "OPTIMAL"
    assert sol["optimization"]["bound"] == 840.0

    # Production minutes: 27819.625...
    # Setup minutes: 840.0
    # Available minutes: 74 * 480 = 35520
    # Free minutes: 35520 - 28659.625 = 6860.375
    # Shifts: 27819.625 / 480 = 57.9575
    # Setup shifts: 840 / 480 = 1.75
    # Free shifts: 6860.375 / 480 = 14.2924
    prod_shifts = sol["net_minutes"] / 480.0
    setup_shifts = sol["setup_minutes"] / 480.0
    free_shifts = (sol["available_minutes"] - sol["net_minutes"] - sol["setup_minutes"]) / 480.0

    assert round(prod_shifts, 2) == 57.96
    assert round(setup_shifts, 2) == 1.75
    assert round(free_shifts, 2) == 14.29

    # Pareto check: 3 SKUs (16816, 5998, 17246) concentrate 62.2%
    p_df = calculate_pareto(demo)
    top_3 = p_df.head(3)
    assert set(top_3["id"]) == {"16816", "5998", "17246"}
    assert round(top_3["pct_load"].sum(), 1) == 62.2


def test_feature2_game_matrix_math(demo):
    """Audits Requirement 2: Mini-game block distance and permutations."""
    families = detect_families(demo)
    block_dist = get_block_matrix(demo, families)

    # 8 families
    assert len(families) == 8

    # Optimal order yields 840 min
    opt_order = ["3533", "3643", "15564", "5998", "6743", "6639", "3278", "3757"]
    res_opt = evaluate_family_sequence(opt_order, families, block_dist)
    assert res_opt["total_minutes"] == 840.0
    assert res_opt["is_optimal"] is True
    assert res_opt["diff_minutes"] == 0.0

    # Incompatible order with transitions costing 180 min
    # E.g. Mostaza (3757) to Piña (6743) is 180 min
    assert block_dist[("3757", "6743")] == 180.0
    bad_order = ["3757", "6743", "3643", "15564", "5998", "6639", "3278", "3533"]
    res_bad = evaluate_family_sequence(bad_order, families, block_dist)
    assert res_bad["total_minutes"] > 840.0
    assert res_bad["is_optimal"] is False
    assert res_bad["diff_minutes"] > 0.0


def test_feature3_sensitivity_simulator(demo):
    """Audits Requirement 3: Sensitivity math, breakeven thresholds, and status."""
    base_net = 27819.625384303745
    base_setup = 840.0

    # L-S Breakeven: (74*480 - 840) / 27819.625 - 1 = +24.66%
    res_be_ls = calculate_sensitivity(base_net, base_setup, 24.66)
    assert abs(res_be_ls["shifts_required"] - 74.0) < 0.05
    assert round(res_be_ls["ls_breakeven_pct"], 1) == 24.7

    # D-D Breakeven: (90*480 - 840) / 27819.625 - 1 = +52.27%
    res_be_dd = calculate_sensitivity(base_net, base_setup, 52.27)
    assert abs(res_be_dd["shifts_required"] - 90.0) < 0.05
    assert round(res_be_dd["dd_breakeven_pct"], 1) == 52.3

    # -20%
    res_neg20 = calculate_sensitivity(base_net, base_setup, -20.0)
    assert res_neg20["status"] == "CABEN_EN_LS"
    assert res_neg20["shifts_required"] < 59.71

    # +60%
    res_pos60 = calculate_sensitivity(base_net, base_setup, 60.0)
    assert res_pos60["status"] == "DESBORDA_PLANTA"
    assert res_pos60["shifts_required"] > 90.0


def test_feature4_matrix_representation(demo):
    """Audits Requirement 4: 17x17 matrix ordered by family and by code."""
    df_fam, ids_fam, labels_fam = get_ordered_matrix(demo, "family")
    df_code, ids_code, labels_code = get_ordered_matrix(demo, "code")

    assert df_fam.shape == (17, 17)
    assert df_code.shape == (17, 17)
    assert set(ids_fam) == set(ids_code) == {p["id"] for p in demo["products"]}

    # In family mode, products of the same family form 0-blocks on the diagonal
    # Mayonesa family (3278, 3749, 7590, 15795, 16816, 17246)
    mayo_ids = ["3278", "3749", "7590", "15795", "16816", "17246"]
    for m1 in mayo_ids:
        for m2 in mayo_ids:
            assert df_fam.loc[m1, m2] == 0.0


def test_feature5_comparative_methods(demo):
    """Audits Requirement 5: Comparison methods, diffs, and worst case."""
    sol = solve(demo)
    comp = get_augmented_comparisons(sol)

    method_map = dict(zip(comp["Método"], comp["Minutos de cambio"]))
    assert any("Óptimo demostrado" in m and method_map[m] == 840.0 for m in method_map)
    assert method_map.get("Vecino más cercano") == 900.0
    assert method_map.get("Demanda descendente") == 1380.0 or method_map.get("Necesidad descendente") == 1380.0
    assert method_map.get("Código ascendente") == 1620.0
    assert any("Peor caso teórico" in m and method_map[m] == 2880.0 for m in method_map)
    assert list(comp["Minutos de cambio"]) == [840.0, 900.0, 1380.0, 1620.0, 2880.0]

    # Check differences in hours
    diff_hours = dict(zip(comp["Método"], comp["Diferencia Horas"]))
    assert diff_hours.get("Vecino más cercano") == 1.0  # +1 h
    assert diff_hours.get("Demanda descendente", diff_hours.get("Necesidad descendente")) == 9.0  # +9 h
    assert diff_hours.get("Código ascendente") == 13.0  # +13 h
    worst_key = [m for m in diff_hours if "Peor caso" in m][0]
    assert diff_hours[worst_key] == 34.0  # +34 h


def test_feature6_scaling_roadmap():
    """Audits Requirement 6: Hoja 13 roadmap criticalities."""
    df_all = get_scaling_data("TODOS")
    assert len(df_all) == 14

    bloq = get_scaling_data("BLOQUEANTE")
    assert len(bloq) == 4
    # Check that SKUs in more than one line and matrices by line are present
    assert any("MÁS DE UNA línea" in item for item in bloq["item"])
    assert any("Matriz de tiempos de cambio" in item for item in bloq["item"])
    assert any("Tasa cartones/turno" in item for item in bloq["item"])

    alto = get_scaling_data("ALTO IMPACTO")
    assert len(alto) == 5
    assert any("alérgenos" in item.lower() for item in alto["item"])
    assert any("paradas programadas" in item.lower() for item in alto["item"])

    ref = get_scaling_data("REFINAMIENTO")
    assert len(ref) == 5
    assert any("costo de turno" in item.lower() for item in ref["item"])
    assert any("oee real" in item.lower() for item in ref["item"])


def test_feature7_excel_export_and_checks(demo):
    """Audits Requirement 7: Audited Excel export integrity."""
    sol = solve(demo)
    raw_bytes = excel_export(sol)
    assert len(raw_bytes) > 1000

    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=False)
    expected_sheets = ["Resumen", "Productos", "Detalle", "Turnos", "Plan por turno", "Cumplimiento", "Escenario", "Cambios"]
    for s in expected_sheets:
        assert s in wb.sheetnames, f"Missing sheet: {s}"

    # Verify that all mathematical checks in solve result evaluate to True
    for check_name, passed in sol["checks"].items():
        assert passed is True, f"Mathematical check failed: {check_name}"


def test_apptest_severe_interactive_lifecycle():
    """Simulate a complete user session with aggressive state transitions in Streamlit."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=45)
    at.run()
    assert not at.exception

    # 1. Stress the Sensitivity Slider through multiple boundary steps
    for delta in [-20, -10, 0, 24, 25, 52, 53, 60]:
        sim_slider = [s for s in at.slider if "demanda" in s.label.lower()][0]
        sim_slider.set_value(delta).run()
        assert not at.exception

    # 2. Toggle Matrix representation back and forth
    matrix_radio = [r for r in at.radio if "matriz" in r.label.lower()][0]
    for opt in matrix_radio.options:
        matrix_radio.set_value(opt).run()
        assert not at.exception

    # 3. Mini-game interactions: Load optimal -> Undo -> Reset -> Random
    opt_btn = [b for b in at.button if "840 min" in b.label][0]
    opt_btn.click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 8

    undo_btn = [b for b in at.button if "Deshacer" in b.label][0]
    undo_btn.click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 7

    reset_btn = [b for b in at.button if "Reiniciar" in b.label][0]
    reset_btn.click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 0

    rand_btn = [b for b in at.button if "aleatorio" in b.label.lower()][0]
    rand_btn.click().run()
    assert not at.exception
    assert len(at.session_state["game_sequence"]) == 8

    # 4. Search box fuzzing inside Streamlit UI with dangerous characters
    search_input = [t for t in at.text_input if "buscar" in t.label.lower()][0]
    for dangerous_char in ["[", "*", "+", "(", "\\"]:
        search_input.set_value(dangerous_char).run()
        assert not at.exception, f"App crashed when user searched for '{dangerous_char}'!"

    # Clear search
    search_input.set_value("").run()
    assert not at.exception


def test_app_empty_products_scenario_lifecycle(demo):
    """Verify that the Streamlit app handles empty products scenario without KeyError or uncaught exceptions."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    empty_scenario = copy.deepcopy(demo)
    empty_scenario["products"] = []
    empty_scenario["matrix"] = {}
    at.session_state["source"] = empty_scenario
    at.session_state["result"] = None
    at.session_state["epoch"] += 1
    at.run()

    # Must survive with zero exceptions (no KeyError: 'shifts_required')
    assert not at.exception, f"App crashed on empty products: {at.exception}"

    # Verify fallback text in executive cards
    md_texts = [m.value for m in at.markdown]
    has_fallback = any("Según capacidad y calendario" in t for t in md_texts)
    assert has_fallback, "Executive card m3 did not display fallback 'Según capacidad y calendario'"

    # Verify mini-game handles empty scenario gracefully
    info_texts = [i.value for i in at.info]
    assert any("No hay familias" in t for t in info_texts), "Mini-game did not show empty families notice"


def test_app_dynamic_executive_card_finish_formatting(demo):
    """Verify dynamic finish date formatting in card m3 for solved vs unfulfilled/missing finish."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Volpak 4 demo finishes on September 24
    md_texts = [m.value for m in at.markdown]
    assert any("24 de septiembre" in t for t in md_texts), "Expected '24 de septiembre' in executive card m3"

    # Simulate scenario with no finish date (unfulfilled)
    sim_result = copy.deepcopy(at.session_state["result"])
    sim_result["finish"] = None
    at.session_state["result"] = sim_result
    at.session_state["epoch"] += 1
    at.run()
    assert not at.exception
    md_texts = [m.value for m in at.markdown]
    assert any("Según capacidad y calendario" in t for t in md_texts), "Expected fallback when finish is None"


def test_app_mini_game_optimal_button_dynamism_and_key_namespacing(demo):
    """Verify that the optimal sequence button adapts dynamically and pick_fam buttons are epoch-namespaced."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Default Volpak 4 demo has 840 min bound
    opt_btn = [b for b in at.button if "840 min" in b.label]
    assert len(opt_btn) == 1, "Expected '★ Cargar secuencia óptima (840 min)' button for Volpak 4"

    # Verify pick_fam button keys have the epoch prefix
    epoch = at.session_state["epoch"]
    pick_buttons = [b for b in at.button if b.key and "pick_fam_" in b.key]
    assert len(pick_buttons) > 0, "Expected family pick buttons"
    for pb in pick_buttons:
        assert pb.key.startswith(f"{epoch}_"), f"Button key '{pb.key}' is not namespaced with epoch {epoch}"


def test_app_dynamic_pareto_banner_content(demo):
    """Verify that the Pareto banner renders dynamic SKU identifiers computed from the scenario."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    info_texts = [i.value for i in at.info]
    pareto_banner = [t for t in info_texts if "Concentración Crítica de Carga" in t]
    assert len(pareto_banner) == 1, "Expected 1 Pareto concentration banner"
    banner_text = pareto_banner[0]

    # Verify dynamically calculated top SKU IDs are present
    assert "16816" in banner_text
    assert "5998" in banner_text
    assert "17246" in banner_text
    assert "62.2%" in banner_text


def test_app_empty_products_initial_boot_metrics(demo):
    """Verify that an empty products scenario correctly renders 0 ctn, 0 shifts, and 0 min."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Swap to empty scenario and re-run
    empty = copy.deepcopy(demo)
    empty["products"] = []
    empty["matrix"] = {}
    at.session_state["source"] = empty
    at.session_state["result"] = None
    at.session_state["epoch"] += 1
    at.run()

    assert not at.exception
    md_texts = " ".join(m.value for m in at.markdown)
    assert '0 <span style="font-size:16px;color:#64748b;">ctn</span>' in md_texts
    assert "Sin productos cargados" in md_texts
    assert "0 / 74" in md_texts
    assert "0 min" in md_texts
    assert "Según capacidad y calendario" in md_texts


def test_app_missing_config_keys_resilience(demo):
    """Verify app does not crash with KeyError if scenario config is partial or missing."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Strip config keys
    scen_no_cfg = copy.deepcopy(demo)
    scen_no_cfg["config"] = {}
    at.session_state["source"] = scen_no_cfg
    at.session_state["epoch"] += 1
    at.run()

    # Must survive without KeyError: 'weekday_shifts', 'factor', or 'year'
    assert not at.exception


def test_app_mini_game_click_optimal_button_reaches_proven_optimum(demo):
    """Verify that clicking the optimal sequence button solves the mini-game and displays the victory banner."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Find the optimal sequence button and click it
    opt_btn = [b for b in at.button if "840 min" in b.label]
    assert len(opt_btn) == 1
    opt_btn[0].click().run()
    assert not at.exception

    # Confirm sequence is now fully loaded with 8 families
    assert len(at.session_state["game_sequence"]) == 8

    # Confirm celebration banner is rendered
    md_texts = " ".join(m.value for m in at.markdown)
    assert "ALCANZASTE EL ÓPTIMO DEMOSTRADO" in md_texts
    assert "840 minutos" in md_texts


def test_app_mode_selector_and_scenario_transition():
    """Verify that toggling between Volpak 4 and Nuevo Escenario works smoothly without error."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Find mode selector
    mode_radios = [r for r in at.radio if "modo" in r.label.lower()]
    assert len(mode_radios) == 1
    mode_radio = mode_radios[0]
    assert len(mode_radio.options) == 2

    # Switch to Nuevo Escenario
    custom_opt = [o for o in mode_radio.options if "Nuevo Escenario" in o][0]
    mode_radio.set_value(custom_opt).run()
    assert not at.exception
    assert at.session_state["app_mode"] == custom_opt

    # Check onboarding expander exists in new scenario mode
    all_subheaders = [s.value for s in at.subheader]
    all_expanders = [e.label for e in at.expander]
    all_md = [m.value for m in at.markdown]
    combined_texts = " ".join(all_subheaders + all_expanders + all_md)
    assert "Marco de Madurez Operativa" in combined_texts or "nuevo escenario" in combined_texts.lower()

    # Switch back to Volpak 4
    volpak_opt = [o for o in mode_radio.options if "Volpak 4" in o][0]
    mode_radio.set_value(volpak_opt).run()
    assert not at.exception
    assert at.session_state["app_mode"] == volpak_opt


def test_app_executive_summary_title_and_chips():
    """Verify elimination of old title and presence of new title and 3 legible capacity chips."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    md_texts = " ".join(m.value for m in at.markdown)
    # Old informal title must be gone
    assert "Trece horas de línea que nadie estaba contando" not in md_texts
    # New executive title and subtitle must be present
    assert "Plan Maestro de Fabricación y Secuenciación Óptima" in md_texts
    assert "Programación matemática de producción mediante minimización de tiempos de cambio" in md_texts

    # High legibility metric chips below capacity bar
    assert "PRODUCCIÓN NETA" in md_texts
    assert "CAMBIOS DE FORMATO" in md_texts
    assert "CAPACIDAD LIBRE" in md_texts


def test_app_scaling_tab_mode_adaptation():
    """Verify that Tab 8 adapts between Volpak 4 Sheet 13 and Operational Maturity Checklist."""
    app_path = str(Path(__file__).resolve().parents[1] / "app.py")
    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()
    assert not at.exception

    # Default Volpak mode shows Volpak 4 question
    md_texts_v4 = " ".join(m.value for m in at.markdown)
    assert "escalar el ejercicio de Volpak 4" in md_texts_v4

    # Switch to Custom mode
    mode_radio = [r for r in at.radio if "modo" in r.label.lower()][0]
    custom_opt = [o for o in mode_radio.options if "Nuevo Escenario" in o][0]
    mode_radio.set_value(custom_opt).run()
    assert not at.exception

    # Now shows Maturity Checklist in subheaders
    all_subheaders = [s.value for s in at.subheader]
    all_md = [m.value for m in at.markdown]
    combined_custom = " ".join(all_subheaders + all_md)
    assert "Marco de Madurez Operativa: Checklist de Viabilidad para Planta Real" in combined_custom
    # Metrics include maturity index
    assert any("Madurez" in m.label for m in at.metric)



