import copy
import io
import itertools
import json
import random
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import fingerprint, make_calendar, route_cost, schedule_route, solve, validate
from io_utils import excel_export


@pytest.fixture
def demo():
    return json.loads((Path(__file__).resolve().parents[1] / "data/demo.json").read_text())


def test_base_case(demo):
    r = solve(demo)
    assert r["optimization"]["status"] == "OPTIMAL"
    assert r["setup_minutes"] == r["optimization"]["bound"] == 840
    assert r["produced"] == r["demand"] == 86331
    assert r["missing"] == 0
    assert len(r["shifts"]) == 74
    assert len(set(r["route"])) == 17
    assert all(r["checks"].values())
    comparisons = {c["method"]: c["setup_minutes"] for c in r["comparison"]}
    assert comparisons["Código ascendente"] == 1620
    assert comparisons["Necesidad descendente"] == 1380
    assert comparisons["Vecino más cercano"] == 900


@pytest.mark.parametrize("seed", [1, 9, 21])
def test_optimizer_matches_exhaustive_search_with_initial_state(demo, seed):
    rng = random.Random(seed)
    demo["products"] = demo["products"][:6]
    ids = [p["id"] for p in demo["products"]]
    demo["matrix"] = {f"{a}|{b}": 0 if a == b else rng.randint(1, 9) for a in ids for b in ids}
    demo["config"]["initial"] = ids[-1]
    exact = min(float(route_cost(demo, list(p))) for p in itertools.permutations(ids))
    result = solve(demo)
    assert result["setup_minutes"] == exact
    assert result["optimization"]["bound"] == exact


def test_no_self_loop_cheat(demo):
    demo["products"] = demo["products"][:4]
    ids = [p["id"] for p in demo["products"]]
    demo["matrix"] = {f"{a}|{b}": 0 if a == b else 120 for a in ids for b in ids}
    assert solve(demo)["setup_minutes"] == 360


def test_shortfall_is_explicit_and_capacity_never_exceeded(demo):
    demo["config"]["factor"] = 2
    r = solve(demo)
    assert r["missing"] > 0 and r["finish"] is None
    assert r["produced"] + r["missing"] == r["demand"]
    assert all(r["checks"].values())
    assert all(round(s["production_minutes"] + s["setup_minutes"], 8) <= s["available_minutes"] for s in r["shifts"])


def test_closed_and_partial_shift(demo):
    demo["closures"] = [{"date": "2026-09-01", "shift": 1, "minutes": 480}, {"date": "2026-09-01", "shift": 2, "minutes": 120}]
    r = solve(demo)
    assert r["available_minutes"] == 74 * 480 - 600
    assert r["shifts"][0]["quantity"] == 0
    assert r["shifts"][1]["available_minutes"] == 360
    assert all(r["checks"].values())


def test_noninteger_rate_short_turns_and_carton_cannot_fit(demo):
    demo["products"] = [dict(demo["products"][0], rate=0.5, demand=10)]
    pid = demo["products"][0]["id"]
    demo["matrix"] = {f"{pid}|{pid}": 0}
    demo["config"]["shift_hours"] = 4
    r = solve(demo)
    assert r["missing"] == 10 and r["produced"] == 0
    assert all(r["checks"].values())


def test_zero_capacity_and_zero_demand(demo):
    for name in ["weekday_shifts", "saturday_shifts", "sunday_shifts"]:
        demo["config"][name] = 0
    r = solve(demo)
    assert r["load_percent"] is None and r["missing"] == 86331
    demo["config"]["factor"] = 0
    r = solve(demo)
    assert r["demand"] == 0 and r["route"] == [] and all(r["checks"].values())


def test_input_validation_and_fingerprint(demo):
    old = fingerprint(demo)
    demo["products"][0]["demand"] += 1
    assert fingerprint(demo) != old
    demo["products"][1]["id"] = demo["products"][0]["id"]
    assert any("únicos" in s for s in validate(demo))
    with pytest.raises(ValueError):
        solve(demo)


def test_missing_change_is_not_zero(demo):
    demo["matrix"]["3533|15564"] = None
    assert any("Faltan" in s for s in validate(demo))


def test_out_of_calendar_closure_rejected(demo):
    demo["closures"] = [{"date": "2026-09-06", "shift": 1, "minutes": 480}]
    assert validate(demo)


def test_runtime_excel_export(demo):
    r = solve(demo)
    data = excel_export(r)
    w = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    assert sum(row[4] for row in w["Detalle"].values if isinstance(row[4], int)) == 86331
    assert w["Turnos"]["H2"].data_type == "f"
    assert w["Plan por turno"].freeze_panes == "C2"


def test_fractional_rate_and_setup_balance(demo):
    demo["products"] = [dict(demo["products"][0], demand=97, rate=99.3), dict(demo["products"][1], demand=71, rate=103.8)]
    ids = [p["id"] for p in demo["products"]]
    demo["matrix"] = {f"{a}|{b}": 0 if a == b else 11.125 for a in ids for b in ids}
    r = solve(demo)
    assert r["produced"] == 168 and all(r["checks"].values())


def test_streamlit_load_and_optimize():
    from streamlit.testing.v1 import AppTest
    path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(path), default_timeout=40).run()
    assert not app.exception
    enter_btns = [b for b in app.button if "Volpak 4" in b.label]
    if enter_btns:
        enter_btns[0].click().run()
        assert not app.exception
    next(b for b in app.button if b.label == "Optimizar y generar plan").click().run()
    assert not app.exception
    assert app.session_state["result"]["missing"] == 0
    base_hash = app.session_state["result"]["fingerprint"]
    next(s for s in app.slider if s.label == "Variación de la necesidad (%)").set_value(20).run()
    assert not app.exception
    assert any("Pendiente de recalcular" in w.value for w in app.warning)
    assert app.session_state["result"]["fingerprint"] == base_hash
    next(b for b in app.button if b.label == "Optimizar y generar plan").click().run()
    assert not app.exception
    assert app.session_state["result"]["fingerprint"] != base_hash
    assert app.session_state["result"]["demand"] > 86331


def test_export_treats_input_as_text(demo):
    demo["products"][0]["description"] = '=HYPERLINK("https://example.com","texto")'
    data = excel_export(solve(demo))
    w = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    assert w["Productos"]["B2"].data_type == "s"
