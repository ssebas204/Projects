"""Single-line setup optimization and auditable integer-carton scheduling."""
from __future__ import annotations

import calendar
import copy
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction

from ortools.sat.python import cp_model

SCALE = 1000  # input precision: 0.001 minute


def fingerprint(scenario):
    return hashlib.sha256(json.dumps(scenario, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate(scenario):
    errors = []
    products = scenario.get("products", [])
    if not products:
        errors.append("Agrega al menos un producto.")
    ids = [str(p.get("id", "")).strip() for p in products]
    if any(not i or "|" in i for i in ids):
        errors.append("Cada código debe tener contenido y no puede incluir |.")
    if len(set(ids)) != len(ids):
        errors.append("Los códigos de producto deben ser únicos.")
    if len(products) > 80:
        errors.append("Esta versión admite hasta 80 productos por escenario.")
    lines = {str(p.get("line", "")).strip() for p in products}
    if len(lines) != 1 or "" in lines:
        errors.append("El escenario debe contener exactamente una línea de fabricación.")
    for p in products:
        for key, name in [("rate", "velocidad"), ("demand", "necesidad")]:
            try:
                value = float(p[key])
                if not math.isfinite(value) or (value <= 0 if key == "rate" else value < 0):
                    raise ValueError()
                if key == "demand" and not value.is_integer():
                    raise ValueError()
            except (TypeError, KeyError, ValueError):
                errors.append(f"{p.get('id', '?')}: {name} inválida. Necesidad entera ≥ 0 y velocidad > 0.")
    matrix = scenario.get("matrix", {})
    missing, bad = [], []
    for a in ids:
        for b in ids:
            value = matrix.get(f"{a}|{b}")
            if value is None:
                missing.append(f"{a} → {b}")
                continue
            try:
                v = Decimal(str(value))
                if not v.is_finite() or v < 0 or v * SCALE != (v * SCALE).to_integral_value() or (a == b and v != 0):
                    raise ValueError()
            except Exception:
                bad.append(f"{a} → {b}")
    if missing:
        errors.append(f"Faltan {len(missing)} tiempos de cambio: {', '.join(missing[:5])}. Completa la matriz; un blanco no significa cero.")
    if bad:
        errors.append(f"Cambios inválidos: {', '.join(bad[:5])}. Usa minutos ≥ 0, máximo tres decimales y diagonal cero.")
    cfg = scenario.get("config", {})
    try:
        date(int(cfg["year"]), int(cfg["month"]), 1)
        hours = int(cfg["shift_hours"])
        if hours not in range(1, 13) or hours != cfg["shift_hours"]:
            raise ValueError()
        for key in ["weekday_shifts", "saturday_shifts", "sunday_shifts"]:
            if int(cfg[key]) != cfg[key] or not 0 <= cfg[key] <= 3 or cfg[key] * hours > 24:
                raise ValueError()
        if not 0 <= cfg["first_hour"] <= 23 or int(cfg["first_hour"]) != cfg["first_hour"]:
            raise ValueError()
        if not math.isfinite(cfg["factor"]) or not 0 <= cfg["factor"] <= 10:
            raise ValueError()
        if cfg.get("initial") is not None and str(cfg["initial"]) not in ids:
            errors.append("El producto inicial debe existir en el maestro, incluso si su necesidad es cero.")
        if not 1 <= float(cfg.get("time_limit", 15)) <= 120:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("Configuración inválida: revisa fechas, turnos, duración, hora de inicio y factor de demanda.")
    seen = set()
    for closed in scenario.get("closures", []):
        try:
            d = date.fromisoformat(closed["date"])
            shift = int(closed["shift"])
            mins = Decimal(str(closed["minutes"]))
            if shift not in (1, 2, 3) or not mins.is_finite() or not 0 <= mins <= int(cfg["shift_hours"]) * 60:
                raise ValueError()
            key = (d.isoformat(), shift)
            if key in seen:
                raise ValueError()
            seen.add(key)
            count = cfg["sunday_shifts"] if d.weekday() == 6 else cfg["saturday_shifts"] if d.weekday() == 5 else cfg["weekday_shifts"]
            if d.year != cfg["year"] or d.month != cfg["month"] or shift > count:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            errors.append("Cada parada debe pertenecer a un turno operativo del mes, sin duplicados, y tener minutos entre cero y la duración del turno.")
            break
    return errors


def effective_products(scenario):
    factor = Decimal(str(scenario.get("config", {}).get("factor", 1.0)))
    return [dict(p, id=str(p["id"]), demand=int((Decimal(str(p["demand"])) * factor).to_integral_value(rounding=ROUND_CEILING))) for p in scenario.get("products", [])]


def cost(scenario, a, b):
    if a is None:
        return 0
    return Fraction(str(scenario["matrix"][f"{a}|{b}"]))


def route_cost(scenario, route):
    return sum((cost(scenario, a, b) for a, b in zip([scenario["config"].get("initial")] + route, route)), Fraction(0))


def optimize_route(scenario):
    ids = sorted(p["id"] for p in effective_products(scenario) if p["demand"] > 0)
    if not ids:
        return {"route": [], "status": "OPTIMAL", "objective": 0.0, "bound": 0.0, "seconds": 0.0}
    model = cp_model.CpModel()
    arcs, variables, terms = [], {}, []
    for i in range(len(ids) + 1):
        for j in range(len(ids) + 1):
            if i == j:  # Self-loops are never decision variables.
                continue
            v = model.new_bool_var(f"arc_{i}_{j}")
            arcs.append((i, j, v))
            variables[i, j] = v
            c = 0 if j == 0 else cost(scenario, scenario["config"].get("initial") if i == 0 else ids[i - 1], ids[j - 1])
            terms.append(int(c * SCALE) * v)
    model.add_circuit(arcs)
    model.minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(scenario["config"].get("time_limit", 15))
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 204
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError("No se obtuvo una secuencia dentro del tiempo permitido. Aumenta el tiempo de resolución.")
    nxt = {i: j for (i, j), v in variables.items() if solver.value(v)}
    route, cur = [], nxt[0]
    while cur:
        if ids[cur - 1] in route:
            raise RuntimeError("Se detectó un ciclo inválido en la solución.")
        route.append(ids[cur - 1])
        cur = nxt[cur]
    if set(route) != set(ids):
        raise RuntimeError("La secuencia no cubre los productos requeridos.")
    return {"route": route, "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE", "objective": float(route_cost(scenario, route)), "bound": solver.best_objective_bound / SCALE, "seconds": solver.wall_time}


def make_calendar(scenario):
    cfg = scenario["config"]
    blocked = {(x["date"], int(x["shift"])): Fraction(str(x["minutes"])) for x in scenario.get("closures", [])}
    slots = []
    for day in range(1, calendar.monthrange(cfg["year"], cfg["month"])[1] + 1):
        d = date(cfg["year"], cfg["month"], day)
        count = cfg["sunday_shifts"] if d.weekday() == 6 else cfg["saturday_shifts"] if d.weekday() == 5 else cfg["weekday_shifts"]
        for shift in range(1, count + 1):
            start = datetime(d.year, d.month, d.day, cfg["first_hour"]) + timedelta(hours=(shift - 1) * cfg["shift_hours"])
            duration = Fraction(cfg["shift_hours"] * 60)
            maintenance = blocked.get((d.isoformat(), shift), Fraction(0))
            slots.append({"date": d.isoformat(), "shift": shift, "start": start, "end": start + timedelta(minutes=float(duration)), "maintenance": maintenance, "available": duration - maintenance, "duration": duration})
    return slots


def schedule_route(scenario, route):
    prods = {p["id"]: p for p in effective_products(scenario)}
    remaining = {i: p["demand"] for i, p in prods.items()}
    slots = make_calendar(scenario)
    details, summary, events = [], [], []
    idx = 0
    setup_left = cost(scenario, scenario["config"].get("initial"), route[0]) if route else Fraction(0)
    total_idle_rounding = Fraction(0)
    completed_at = None
    for slot in slots:
        avail = slot["available"]
        cursor = slot["start"] + timedelta(minutes=float(slot["maintenance"]))
        used_prod, used_setup, rounding, cartons = Fraction(0), Fraction(0), Fraction(0), 0
        if slot["maintenance"]:
            events.append({"start": slot["start"].isoformat(), "end": cursor.isoformat(), "type": "Parada", "product": "Mantenimiento", "quantity": 0})
        while idx < len(route) and avail > 0:
            pid = route[idx]
            if setup_left:
                used = min(avail, setup_left)
                end = cursor + timedelta(minutes=float(used))
                events.append({"start": cursor.isoformat(), "end": end.isoformat(), "type": "Cambio", "product": pid, "quantity": 0})
                details.append({"date": slot["date"], "shift": slot["shift"], "id": pid, "description": prods[pid]["description"], "quantity": 0, "production_minutes": 0.0, "setup_minutes": float(used)})
                avail -= used
                setup_left -= used
                used_setup += used
                cursor = end
                if setup_left or not avail:
                    break
            unit = Fraction(480) / Fraction(str(prods[pid]["rate"]))
            qty = min(remaining[pid], int(avail // unit))
            used = qty * unit
            if qty:
                end = cursor + timedelta(minutes=float(used))
                events.append({"start": cursor.isoformat(), "end": end.isoformat(), "type": "Producción", "product": pid, "quantity": qty})
                details.append({"date": slot["date"], "shift": slot["shift"], "id": pid, "description": prods[pid]["description"], "quantity": qty, "production_minutes": float(used), "setup_minutes": 0.0})
                cursor = end
                used_prod += used
                cartons += qty
                avail -= used
                remaining[pid] -= qty
                completed_at = end
            if remaining[pid]:
                rounding = avail
                total_idle_rounding += rounding
                break
            idx += 1
            if idx < len(route):
                setup_left = cost(scenario, pid, route[idx])
        if avail:
            events.append({"start": cursor.isoformat(), "end": slot["end"].isoformat(), "type": "Libre", "product": "Sin asignación", "quantity": 0})
        summary.append({"date": slot["date"], "shift": slot["shift"], "available_minutes": float(slot["available"]), "maintenance_minutes": float(slot["maintenance"]), "production_minutes": float(used_prod), "setup_minutes": float(used_setup), "idle_minutes": float(avail), "rounding_minutes": float(rounding), "quantity": cartons})
    total_need = sum(p["demand"] for p in prods.values())
    made = {pid: prods[pid]["demand"] - rem for pid, rem in remaining.items()}
    missing = sum(remaining.values())
    net_minutes = sum((Fraction(p["demand"]) * 480 / Fraction(str(p["rate"])) for p in prods.values()), Fraction(0))
    available = sum((s["available"] for s in slots), Fraction(0))
    setup_all = route_cost(scenario, route)
    # Independent capacity checks: do not grant an operational tolerance.
    checks = {
        "Productos distintos y completos en la secuencia": len(route) == len(set(route)) and set(route) == {p["id"] for p in prods.values() if p["demand"] > 0},
        "Cantidad programada + pendiente = necesidad": all(made[i] + remaining[i] == prods[i]["demand"] for i in prods),
        "Cantidades enteras y no negativas": all(isinstance(d["quantity"], int) and d["quantity"] >= 0 for d in details),
        "Capacidad respetada por turno": all(round(s["production_minutes"] + s["setup_minutes"], 8) <= round(s["available_minutes"], 8) for s in summary),
        "Tiempo disponible reconciliado": all(abs(s["production_minutes"] + s["setup_minutes"] + s["idle_minutes"] - s["available_minutes"]) < 1e-7 for s in summary),
    }
    if missing == 0:
        checks["Tiempo productivo y cambios reconciliados"] = abs(sum(d["production_minutes"] for d in details) - float(net_minutes)) < 1e-6 and abs(sum(d["setup_minutes"] for d in details) - float(setup_all)) < 1e-6
    return {"details": details, "shifts": summary, "events": events, "remaining": remaining, "made": made, "checks": checks,
            "demand": total_need, "produced": total_need - missing, "missing": missing,
            "net_minutes": float(net_minutes), "setup_minutes": float(setup_all), "available_minutes": float(available),
            "rounding_minutes": float(total_idle_rounding), "load_percent": float((net_minutes + setup_all) / available * 100) if available else None,
            "finish": completed_at.isoformat() if missing == 0 and completed_at else None,
            "capacity_shortfall_minutes": float(max(Fraction(0), net_minutes + setup_all - available)),
            "route": route}


def solve(scenario):
    scenario = copy.deepcopy(scenario)
    errors = validate(scenario)
    if errors:
        raise ValueError("\n".join(errors))
    solution = optimize_route(scenario)
    plan = schedule_route(scenario, solution["route"])
    products = [p for p in effective_products(scenario) if p["demand"] > 0]
    code = sorted((p["id"] for p in products), key=lambda x: (0, int(x)) if x.isdigit() else (1, x))
    demand = [p["id"] for p in sorted(products, key=lambda p: (-p["demand"], p["id"]))]
    left, greedy = set(code), []
    if code:
        greedy = [code[0]]
        left.remove(code[0])
    while left:
        nxt = min(left, key=lambda p: (cost(scenario, greedy[-1], p), (0, int(p)) if p.isdigit() else (1, p)))
        greedy.append(nxt)
        left.remove(nxt)
    comparison = []
    for label, route in [("Optimización", solution["route"]), ("Código ascendente", code), ("Necesidad descendente", demand), ("Vecino más cercano", greedy)]:
        trial = plan if label == "Optimización" else schedule_route(scenario, route)
        comparison.append({"method": label, "setup_minutes": float(route_cost(scenario, route)), "pending": trial["missing"], "finish": trial["finish"], "route": route})
    return dict(plan, optimization=solution, comparison=comparison, fingerprint=fingerprint(scenario), scenario=scenario)
