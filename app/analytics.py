"""Analytics, sensitivity simulation, family clustering, and plant scaling data."""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from engine import cost, effective_products, route_cost


# ---------------------------------------------------------------------------
# 1. FAMILY DETECTION & BLOCK MATRIX (Connected Components of 0-cost transitions)
# ---------------------------------------------------------------------------

DEFAULT_FAMILY_NAMES = {
    "3533": "S5 Vinagre",
    "3643": "S4 Rosada",
    "15564": "S3 Napolitana",
    "5998": "F3 Tomate",
    "15881": "F3 Tomate",
    "16787": "F3 Tomate",
    "6743": "S2 Piña",
    "6639": "S1 Barbecue",
    "3278": "F2 Emulsiones",
    "3749": "F2 Emulsiones",
    "7590": "F2 Emulsiones",
    "15795": "F2 Emulsiones",
    "16816": "F2 Emulsiones",
    "17246": "F2 Emulsiones",
    "3757": "F1 Mostazas",
    "3925": "F1 Mostazas",
    "6616": "F1 Mostazas",
}


def detect_families(scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Partition products into families based on 0-cost transitions.
    
    Two products belong to the same family if there is a path of 0-cost transitions
    between them in the changeover matrix.
    """
    products = scenario.get("products", [])
    matrix = scenario.get("matrix", {})
    ids = [str(p["id"]) for p in products]

    adj = {i: set() for i in ids}
    for a in ids:
        for b in ids:
            if a != b:
                val_ab = matrix.get(f"{a}|{b}")
                val_ba = matrix.get(f"{b}|{a}")
                if val_ab == 0 and (val_ba == 0 or val_ba is None):
                    adj[a].add(b)
                    adj[b].add(a)

    visited = set()
    families = []
    
    # Sort order to have deterministic family discovery
    id_sort_key = lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))
    sorted_ids = sorted(ids, key=id_sort_key)

    for pid in sorted_ids:
        if pid not in visited:
            comp = []
            queue = [pid]
            visited.add(pid)
            for node in queue:
                comp.append(node)
                for neighbor in sorted(adj[node], key=id_sort_key):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            
            comp_sorted = sorted(comp, key=id_sort_key)
            rep_id = comp_sorted[0]
            
            # Use known domain name if available, else derive from representative
            rep_prod = next((p for p in products if str(p["id"]) == rep_id), None)
            rep_desc = rep_prod.get("description", "") if rep_prod else rep_id
            
            # Short recognizable label
            family_name = DEFAULT_FAMILY_NAMES.get(rep_id)
            if not family_name:
                family_name = f"Familia {rep_id} ({rep_desc[:15].strip()})"
                
            families.append({
                "id": rep_id,
                "name": family_name,
                "rep_id": rep_id,
                "members": comp_sorted,
                "member_names": [
                    next((p.get("description", m) for p in products if str(p["id"]) == m), m)
                    for m in comp_sorted
                ]
            })

    return families


def get_block_matrix(scenario: Dict[str, Any], families: List[Dict[str, Any]]) -> Dict[Tuple[str, str], float]:
    """Compute minimal transition cost between all pairs of families."""
    matrix = scenario.get("matrix", {})
    block_dist = {}
    for f1 in families:
        id1 = f1["id"]
        for f2 in families:
            id2 = f2["id"]
            if id1 == id2:
                block_dist[(id1, id2)] = 0.0
            else:
                costs = [
                    float(matrix.get(f"{m1}|{m2}", 180.0))
                    for m1 in f1["members"]
                    for m2 in f2["members"]
                ]
                block_dist[(id1, id2)] = min(costs) if costs else 120.0
    return block_dist


def evaluate_family_sequence(
    sequence: List[str],
    families: List[Dict[str, Any]],
    block_dist: Dict[Tuple[str, str], float]
) -> Dict[str, Any]:
    """Evaluate a user-constructed sequence of family IDs.
    
    Returns total minutes, hours, transitions detail, comparison vs 840 min optimum.
    """
    fam_by_id = {f["id"]: f for f in families}
    if not sequence or len(sequence) < 2:
        return {
            "total_minutes": 0.0,
            "total_hours": 0.0,
            "transitions": [],
            "diff_minutes": 0.0,
            "diff_hours": 0.0,
            "is_optimal": False,
            "is_complete": False,
            "count": len(sequence),
            "total_families": len(families)
        }

    total_cost = 0.0
    transitions = []
    for i in range(len(sequence) - 1):
        orig_id = sequence[i]
        dest_id = sequence[i + 1]
        step_cost = block_dist.get((orig_id, dest_id), 120.0)
        total_cost += step_cost
        orig_name = fam_by_id.get(orig_id, {}).get("name", orig_id)
        dest_name = fam_by_id.get(dest_id, {}).get("name", dest_id)
        transitions.append({
            "step": i + 1,
            "from_id": orig_id,
            "from_name": orig_name,
            "to_id": dest_id,
            "to_name": dest_name,
            "cost_minutes": step_cost,
            "is_incompatible": step_cost > 120.0
        })

    is_complete = len(sequence) == len(families)
    is_optimal = is_complete and (total_cost == 840.0)
    diff = total_cost - 840.0

    return {
        "total_minutes": total_cost,
        "total_hours": total_cost / 60.0,
        "transitions": transitions,
        "diff_minutes": diff,
        "diff_hours": diff / 60.0,
        "is_optimal": is_optimal,
        "is_complete": is_complete,
        "count": len(sequence),
        "total_families": len(families)
    }


# ---------------------------------------------------------------------------
# 2. ABC / PARETO ANALYSIS
# ---------------------------------------------------------------------------

def calculate_pareto(scenario: Dict[str, Any]) -> pd.DataFrame:
    """Compute ABC / Pareto load breakdown by SKU in turns and net minutes."""
    products = effective_products(scenario)
    rows = []
    total_net_minutes = 0.0

    for p in products:
        pid = str(p["id"])
        demand = float(p.get("demand", 0))
        rate = float(p.get("rate", 1))
        # Net production minutes: demand * (480 / rate)
        mins = demand * 480.0 / rate if rate > 0 else 0.0
        # Required shifts
        shifts = mins / 480.0
        total_net_minutes += mins
        rows.append({
            "id": pid,
            "description": p.get("description", pid),
            "demand": demand,
            "rate": rate,
            "production_minutes": mins,
            "shifts_required": shifts
        })

    df = pd.DataFrame(rows)
    if df.empty or total_net_minutes == 0:
        df["pct_load"] = 0.0
        df["cum_pct"] = 0.0
        df["zone"] = "C"
        return df

    # Sort descending by production load
    df = df.sort_values(by="production_minutes", ascending=False).reset_index(drop=True)
    df["pct_load"] = (df["production_minutes"] / total_net_minutes) * 100.0
    df["cum_pct"] = df["pct_load"].cumsum()

    # Classify Zones
    def assign_zone(cum: float) -> str:
        if cum <= 80.01:
            return "A"
        elif cum <= 95.01:
            return "B"
        return "C"

    df["zone"] = df["cum_pct"].apply(assign_zone)
    return df


def get_pareto_key_insights(df_pareto: pd.DataFrame) -> Dict[str, Any]:
    """Calculate specific Pareto insights (e.g. top 3 concentration)."""
    if df_pareto.empty:
        return {"top_3_pct": 0.0, "top_3_skus": [], "zone_a_count": 0}

    top_3 = df_pareto.head(3)
    top_3_pct = float(top_3["pct_load"].sum()) if not top_3.empty else 0.0
    top_3_skus = [
        f"{r['id']} {r['description'][:25]}" for _, r in top_3.iterrows()
    ]
    zone_a_count = int((df_pareto["zone"] == "A").sum())

    return {
        "top_3_pct": round(top_3_pct, 1),
        "top_3_skus": top_3_skus,
        "zone_a_count": zone_a_count,
        "total_skus": len(df_pareto)
    }


# ---------------------------------------------------------------------------
# 3. SENSITIVITY SIMULATOR & CAPACITY ANALYSIS (-20% to +60%)
# ---------------------------------------------------------------------------

LS_CAPACITY_SHIFTS = 74  # Mon - Sat
DD_CAPACITY_SHIFTS = 90  # Sun - Sun
SHIFT_HOURS = 8
MINUTES_PER_SHIFT = 480


def calculate_sensitivity(
    base_net_minutes: float,
    base_setup_minutes: float = 840.0,
    factor_percent: float = 0.0,
    ls_shifts: int = LS_CAPACITY_SHIFTS,
    dd_shifts: int = DD_CAPACITY_SHIFTS
) -> Dict[str, Any]:
    """Calculate sensitivity metrics for a given demand delta percentage."""
    delta = factor_percent / 100.0
    multiplier = 1.0 + delta

    # Net production scales linearly; setup is fixed (1 campaign per SKU)
    prod_minutes = base_net_minutes * multiplier
    total_minutes = prod_minutes + base_setup_minutes
    shifts_required = total_minutes / MINUTES_PER_SHIFT

    ls_available_minutes = ls_shifts * MINUTES_PER_SHIFT
    dd_available_minutes = dd_shifts * MINUTES_PER_SHIFT

    # Theoretical breakeven growth points
    ls_breakeven_pct = (
        (ls_available_minutes - base_setup_minutes) / base_net_minutes - 1.0
    ) * 100.0 if base_net_minutes > 0 else 0.0

    dd_breakeven_pct = (
        (dd_available_minutes - base_setup_minutes) / base_net_minutes - 1.0
    ) * 100.0 if base_net_minutes > 0 else 0.0

    # Status classification
    if shifts_required <= ls_shifts:
        status = "CABEN_EN_LS"
        status_label = "Capacidad Holgada: Cabe en Régimen Lunes a Sábado"
        status_color = "#10b981"  # Emerald green
        slack_ls_shifts = ls_shifts - shifts_required
        slack_ls_hours = slack_ls_shifts * SHIFT_HOURS
        deficit_shifts = 0.0
    elif shifts_required <= dd_shifts:
        status = "REQUIERE_DD"
        status_label = "Atención: Supera Lunes a Sábado · Requiere Régimen Domingo a Domingo"
        status_color = "#f59e0b"  # Amber
        slack_ls_shifts = -(shifts_required - ls_shifts)
        slack_ls_hours = slack_ls_shifts * SHIFT_HOURS
        deficit_shifts = 0.0
    else:
        status = "DESBORDA_PLANTA"
        status_label = "Alerta Crítica: Desborda Capacidad Máxima de Planta (D-D)"
        status_color = "#ef4444"  # Red
        slack_ls_shifts = -(shifts_required - ls_shifts)
        slack_ls_hours = slack_ls_shifts * SHIFT_HOURS
        deficit_shifts = shifts_required - dd_shifts

    utilization_ls = (shifts_required / ls_shifts) * 100.0 if ls_shifts > 0 else 0.0
    utilization_dd = (shifts_required / dd_shifts) * 100.0 if dd_shifts > 0 else 0.0

    return {
        "factor_percent": factor_percent,
        "multiplier": multiplier,
        "production_minutes": prod_minutes,
        "setup_minutes": base_setup_minutes,
        "total_minutes": total_minutes,
        "shifts_required": shifts_required,
        "hours_required": total_minutes / 60.0,
        "ls_shifts": ls_shifts,
        "dd_shifts": dd_shifts,
        "utilization_ls_pct": utilization_ls,
        "utilization_dd_pct": utilization_dd,
        "ls_breakeven_pct": ls_breakeven_pct,
        "dd_breakeven_pct": dd_breakeven_pct,
        "status": status,
        "status_label": status_label,
        "status_color": status_color,
        "slack_ls_shifts": slack_ls_shifts,
        "slack_ls_hours": slack_ls_hours,
        "deficit_shifts": deficit_shifts
    }


def generate_sensitivity_table(
    base_net_minutes: float,
    base_setup_minutes: float = 840.0,
    base_demand: int = 86331,
    points: Optional[List[float]] = None
) -> pd.DataFrame:
    """Generate discrete sensitivity table across standard scenario steps."""
    if points is None:
        points = [-20.0, -10.0, 0.0, 10.0, 20.0, 24.66, 30.0, 40.0, 50.0, 52.27, 60.0]

    rows = []
    for p in points:
        res = calculate_sensitivity(base_net_minutes, base_setup_minutes, p)
        dem = round(base_demand * (1.0 + p / 100.0))
        label = f"Base ({dem:,})" if abs(p) < 0.01 else (
            f"Quiebre L-S (+{p:.1f}%)" if abs(p - 24.66) < 0.1 else (
                f"Quiebre D-D (+{p:.1f}%)" if abs(p - 52.27) < 0.1 else f"{p:+.0f}%"
            )
        )
        rows.append({
            "Escenario": label,
            "Variación (%)": p,
            "Demanda (cartones)": dem,
            "Min Producción": round(res["production_minutes"], 1),
            "Min Cambio": round(res["setup_minutes"], 1),
            "Min Totales": round(res["total_minutes"], 1),
            "Turnos Requeridos": round(res["shifts_required"], 2),
            "Ocupación L-S (%)": round(res["utilization_ls_pct"], 1),
            "Estado": "L-S Factible" if res["status"] == "CABEN_EN_LS" else (
                "Requiere D-D" if res["status"] == "REQUIERE_DD" else "Desborde"
            )
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. MATRIX ORDERING (BY CODE vs BY FAMILY)
# ---------------------------------------------------------------------------

def get_ordered_matrix(scenario: Dict[str, Any], order_by: str = "family") -> Tuple[pd.DataFrame, List[str], List[str]]:
    """Return changeover matrix ordered either 'code' (numerical) or 'family'."""
    products = scenario.get("products", [])
    matrix = scenario.get("matrix", {})
    
    if order_by == "family":
        families = detect_families(scenario)
        # Flatten ordered by family
        ordered_ids = []
        for fam in families:
            ordered_ids.extend(fam["members"])
    else:
        id_sort_key = lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x))
        ordered_ids = sorted([str(p["id"]) for p in products], key=id_sort_key)

    prods_by_id = {str(p["id"]): p for p in products}
    labels = [
        f"{pid} · {prods_by_id.get(pid, {}).get('description', '')[:14]}"
        for pid in ordered_ids
    ]

    grid = []
    for a in ordered_ids:
        row = []
        for b in ordered_ids:
            val = matrix.get(f"{a}|{b}", 0 if a == b else None)
            row.append(float(val) if val is not None else 0.0)
        grid.append(row)

    df_matrix = pd.DataFrame(grid, index=ordered_ids, columns=ordered_ids)
    return df_matrix, ordered_ids, labels


# ---------------------------------------------------------------------------
# 5. METHODS COMPARISON (WITH THEORETICAL WORST CASE)
# ---------------------------------------------------------------------------

THEORETICAL_WORST_CASE_MINUTES = 2880.0  # 16 transitions * 180 min


def get_augmented_comparisons(result: Dict[str, Any]) -> pd.DataFrame:
    """Return comparison table augmented with theoretical worst case and diffs."""
    base_comp = result.get("comparison", [])
    opt_mins = float(result.get("setup_minutes", 840.0))

    rows = []
    for item in base_comp:
        method = item["method"]
        mins = float(item["setup_minutes"])
        diff_mins = mins - opt_mins
        diff_hours = diff_mins / 60.0
        
        # Display friendly label
        if method == "Optimización":
            label = "Óptimo demostrado (TSP exacto)"
            badge = "Demostrado"
            finish = result.get("finish")
        else:
            label = method
            badge = f"+{diff_hours:.1f} h" if diff_hours > 0 else "0 h"
            finish = item.get("finish")

        finish_str = "24/09 17:15" if finish and "2026-09-24" in str(finish) else (
            str(finish)[:16] if finish else "—"
        )

        rows.append({
            "Método": label,
            "Minutos de cambio": mins,
            "Horas de cambio": mins / 60.0,
            "Diferencia vs Óptimo": f"+{int(diff_mins)} min (+{diff_hours:.1f} h)" if diff_mins > 0 else "0 min (Base)",
            "Diferencia Horas": diff_hours,
            "Cierre estimado": finish_str,
            "Cartones pendientes": item.get("pending", 0),
            "Tipo": "Algoritmo"
        })

    # Add Theoretical Worst Case (16 changes of 180 min = 2,880 min / 48 h)
    worst_diff_mins = THEORETICAL_WORST_CASE_MINUTES - opt_mins
    worst_diff_hours = worst_diff_mins / 60.0
    rows.append({
        "Método": "Peor caso teórico (16 × 180 min)",
        "Minutos de cambio": THEORETICAL_WORST_CASE_MINUTES,
        "Horas de cambio": THEORETICAL_WORST_CASE_MINUTES / 60.0,
        "Diferencia vs Óptimo": f"+{int(worst_diff_mins)} min (+{worst_diff_hours:.1f} h)",
        "Diferencia Horas": worst_diff_hours,
        "Cierre estimado": "Desborde horizonte",
        "Cartones pendientes": 0,
        "Tipo": "Referencia Teórica"
    })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 6. PLANT SCALING MODULE (EXCEL SHEET 13 DATA MODEL)
# ---------------------------------------------------------------------------

SCALING_DATA = [
    {
        "num": 1,
        "item": "Asignación producto → línea de las demás líneas",
        "reason": "Sin saber qué SKU corre en qué línea no se puede replicar el ejercicio fuera de Volpak 4.",
        "impact": "Adaptar datos, rangos, familias y calendario por línea; validar el modelo antes de usarlo.",
        "criticality": "BLOQUEANTE",
        "color": "#ef4444"
    },
    {
        "num": 2,
        "item": "SKUs que pueden correr en MÁS DE UNA línea",
        "reason": "Es el dato más importante que falta. Si un producto puede ir en dos líneas, la decisión ya no es sólo en qué orden fabricar, sino también dónde.",
        "impact": "El problema deja de ser secuenciación pura y pasa a ser asignación + secuenciación simultáneas (máquinas paralelas no relacionadas).",
        "criticality": "BLOQUEANTE",
        "color": "#ef4444"
    },
    {
        "num": 3,
        "item": "Matriz de tiempos de cambio de cada línea",
        "reason": "Cada línea tiene su propia mecánica de montaje: la matriz de cambios no es trasladable.",
        "impact": "Cada matriz requiere revisar agrupaciones, restricciones cruzadas y ejecutar la optimización.",
        "criticality": "BLOQUEANTE",
        "color": "#ef4444"
    },
    {
        "num": 4,
        "item": "Tasa cartones/turno por producto y por línea",
        "reason": "La velocidad de un mismo SKU cambia según la máquina donde se monte.",
        "impact": "Permite comparar líneas y decidir dónde conviene cargar cada producto.",
        "criticality": "BLOQUEANTE",
        "color": "#ef4444"
    },
    {
        "num": 5,
        "item": "Unidad y definición de necesidad; inventarios",
        "reason": "Confirmar que la necesidad está en cartones y si ya descuenta inventario y contempla stock de seguridad.",
        "impact": "Usar necesidad neta confirmada. Evita restar inventarios doblemente.",
        "criticality": "ALTO IMPACTO",
        "color": "#f59e0b"
    },
    {
        "num": 6,
        "item": "Fecha de requerimiento de cada SKU dentro del mes",
        "reason": "La demanda llega agregada al mes. Con fechas intermedias, el orden por cambios puede incumplir entregas.",
        "impact": "El objetivo pasa a ser doble: mínimo cambio con cero incumplimientos de fechas intermedias.",
        "criticality": "ALTO IMPACTO",
        "color": "#f59e0b"
    },
    {
        "num": 7,
        "item": "Último producto fabricado en agosto en cada línea",
        "reason": "Define el montaje inicial con el que arranca el mes y por lo tanto el costo del primer cambio.",
        "impact": "Fija el nodo de origen del camino en lugar de dejarlo abierto.",
        "criticality": "ALTO IMPACTO",
        "color": "#f59e0b"
    },
    {
        "num": 8,
        "item": "Paradas programadas: mantenimiento, sanitización, festivos",
        "reason": "Un turno bloqueado por mantenimiento no es capacidad disponible de envasado.",
        "impact": "Adaptar fechas y espacios de turno; revisar continuidad de campañas al retirar turnos.",
        "criticality": "ALTO IMPACTO",
        "color": "#f59e0b"
    },
    {
        "num": 9,
        "item": "Reglas de alérgenos y secuencias prohibidas",
        "reason": "En alimentos hay pares de productos que no pueden ir seguidos por contaminación cruzada.",
        "impact": "Se agregan restricciones x(i,j) = 0 sobre los pares prohibidos sin alterar el solver.",
        "criticality": "ALTO IMPACTO",
        "color": "#f59e0b"
    },
    {
        "num": 10,
        "item": "OEE real y merma por SKU",
        "reason": "Permite saber si la tasa cartones/turno es teórica de placa o producción real esperada.",
        "impact": "Ajusta los tiempos de producción y por lo tanto la carga total de planta.",
        "criticality": "REFINAMIENTO",
        "color": "#10b981"
    },
    {
        "num": 11,
        "item": "Lote mínimo y máximo por campaña, y vida útil",
        "reason": "Determina si es viable fabricar toda la necesidad de un SKU de corrido en una sola campaña.",
        "impact": "Obliga a fraccionar campañas: lot-sizing capacitado con setups (CLSD).",
        "criticality": "REFINAMIENTO",
        "color": "#10b981"
    },
    {
        "num": 12,
        "item": "Disponibilidad de material de empaque y capacidad aguas arriba",
        "reason": "No es posible programar un turno si no hay bobina/doypack o no hay producto formulado en cocina.",
        "impact": "Agrega restricciones de disponibilidad de insumos por período.",
        "criticality": "REFINAMIENTO",
        "color": "#10b981"
    },
    {
        "num": 13,
        "item": "Costo de turno, recargo nocturno y dominical",
        "reason": "Hoy se minimiza TIEMPO. Con costos monetarios se optimiza DINERO, que no es lo mismo.",
        "impact": "Función objetivo de costo total: cambios + mano de obra + recargos dominicales.",
        "criticality": "REFINAMIENTO",
        "color": "#10b981"
    },
    {
        "num": 14,
        "item": "Capacidad de almacenamiento de producto terminado",
        "reason": "Campañas grandes generan picos de inventario que la bodega puede no ser capaz de absorber.",
        "impact": "Agrega restricciones de inventario máximo en almacén por período.",
        "criticality": "REFINAMIENTO",
        "color": "#10b981"
    }
]


def get_scaling_data(criticality_filter: Optional[str] = None) -> pd.DataFrame:
    """Return scaling roadmap table with optional criticality filter."""
    data = SCALING_DATA
    if criticality_filter and criticality_filter != "TODOS":
        data = [d for d in data if d["criticality"].upper() == criticality_filter.upper()]
    return pd.DataFrame(data)
