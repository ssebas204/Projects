from __future__ import annotations

import copy
import html
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from engine import effective_products, fingerprint, solve, validate
from io_utils import excel_export, import_three
st.set_page_config(page_title="Planificador de fabricación", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.stApp {background:#f5f7fb;}
.block-container {padding-top:4.5rem;max-width:1400px;}
h1,h2,h3 {letter-spacing:-.025em;}
.app-header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid #dce3ee;padding:0 0 16px;margin-bottom:18px;}
.app-header h1{font-size:27px;font-weight:600;color:#24364d;margin:0;padding:0;}
.app-header span{font-size:14px;color:#52637c;}
[data-testid="stMetric"]{background:white;border:1px solid #dce3ee;border-radius:8px;padding:14px;}
[data-testid="stMetricLabel"]{font-size:13px;color:#52637c;}
.stButton button[kind="primary"]{background:#245cd4;border-color:#245cd4;}
div[data-testid="stTabs"] button{font-size:15px;}
@media(max-width:600px){.app-header h1{font-size:22px;}.block-container{padding-left:1rem;padding-right:1rem;}}
</style>""", unsafe_allow_html=True)


def demo():
    return json.loads((ROOT / "data/demo.json").read_text())


def replace_scenario(value):
    st.session_state.source = value
    st.session_state.epoch += 1
    st.session_state.result = None
    st.rerun()


def pretty(n, digits=0):
    if n is None:
        return "—"
    return f"{n:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


if "source" not in st.session_state:
    st.session_state.source = demo()
    st.session_state.epoch = 0
    st.session_state.result = None
    st.session_state.saved = {}

source = st.session_state.source
epoch = st.session_state.epoch
key = lambda name: f"{epoch}_{name}"
cfg = source["config"]

st.markdown('<div class="app-header"><h1>Planificador de fabricación</h1><span>by: Sebastian Parra</span></div>', unsafe_allow_html=True)
context = st.columns([2, 2, 1])
name = context[0].text_input("Nombre del escenario", value=source["name"], key=key("name"))
selected_month = context[1].date_input("Mes de fabricación", value=date(cfg["year"], cfg["month"], 1), key=key("month"), help="Se utiliza todo el mes de la fecha seleccionada.")
context[2].markdown("**Línea**")
context[2].write(", ".join(dict.fromkeys(str(p["line"]) for p in source["products"])))

steps = ["1 · Productos y demanda", "2 · Calendario", "3 · Plan de fabricación"]
def go_step(index):
    st.session_state.workflow = steps[index]

if "next_step" in st.session_state:
    go_step(st.session_state.pop("next_step"))
tabs = st.tabs(steps, key="workflow", on_change="rerun")

with tabs[1]:
    st.subheader("¿Cuándo puede trabajar la línea?")
    st.caption("Configura los turnos y las paradas para el mes seleccionado.")
    days = st.columns(3)
    weekday = days[0].number_input("Turnos de lunes a viernes", 0, 3, cfg["weekday_shifts"], key=key("weekday"))
    saturday = days[1].number_input("Turnos del sábado", 0, 3, cfg["saturday_shifts"], key=key("saturday"))
    sunday = days[2].number_input("Turnos del domingo", 0, 3, cfg["sunday_shifts"], key=key("sunday"))
    timing = st.columns(2)
    hours = timing[0].number_input("Horas por turno", 1, 12, cfg["shift_hours"], key=key("hours"))
    first_hour = timing[1].number_input("Hora de inicio del turno 1", 0, 23, cfg["first_hour"], key=key("first_hour"))
    import calendar
    shift_count = sum(weekday if date(selected_month.year, selected_month.month, day).weekday() < 5 else saturday if date(selected_month.year, selected_month.month, day).weekday() == 5 else sunday for day in range(1, calendar.monthrange(selected_month.year, selected_month.month)[1]+1))
    st.info(f"{shift_count} turnos · {shift_count * hours} horas antes de descontar paradas.")
    st.caption("La fecha identifica el día operativo. El último turno puede terminar al día siguiente.")
    with st.expander("Ajustes del escenario y optimización"):
        growth = st.slider("Variación de la necesidad (%)", -100, 900, int(round((cfg["factor"] - 1) * 100)), key=key("growth"))
        st.caption("Se aplica a todos los productos y se redondea hacia arriba a cartones completos.")
        limit = st.number_input("Tiempo máximo de optimización (segundos)", 1, 120, int(cfg.get("time_limit", 15)), key=key("limit"))
    calendar_details = st.container()
    calendar_actions = st.container()

with tabs[0]:
    st.subheader("¿Qué necesitas fabricar?")
    st.caption("Edita los datos cargados o reemplázalos con los tres archivos Excel.")
    st.caption(f"{len(source['products'])} productos cargados · Una línea por escenario")
    with st.expander("Cargar los tres archivos Excel", expanded=True):
        cols = st.columns(3)
        assignment = cols[0].file_uploader("Asignación de productos", type=["xlsx"], key=key("assignment"))
        demand_file = cols[1].file_uploader("Necesidad de fabricación", type=["xlsx"], key=key("demand_file"))
        matrix_file = cols[2].file_uploader("Matriz de cambios", type=["xlsx"], key=key("matrix_file"))
        st.caption("Conserva los encabezados y el orden de columnas de los archivos originales. Se lee la primera hoja de cada archivo.")
        with st.expander("Ver la estructura de los archivos"):
            st.markdown("**Asignación de productos:** Linea Producción · Id Producto asignado · Descripción Producto asignado · Presentación · Formato gr · Cartones/Turno")
            st.markdown("**Necesidad de fabricación:** Id Producto · Descripción Producto · Necesidad Fabricación")
            st.markdown("**Matriz de tiempos de cambio:** códigos de producto en la primera fila y la primera columna; tiempos en minutos en las intersecciones.")
            st.caption("La necesidad se expresa en cartones. Cartones/Turno corresponde a la capacidad por 8 horas. Los códigos deben coincidir entre los tres archivos.")
        if st.button("Cargar los tres Excel", disabled=not all([assignment, demand_file, matrix_file])):
            try:
                loaded = import_three(assignment.getvalue(), demand_file.getvalue(), matrix_file.getvalue(), cfg)
                issues = validate(loaded)
                if issues:
                    st.error("\n\n".join(issues))
                else:
                    replace_scenario(loaded)
            except Exception as exc:
                st.error(f"No se pudo importar: {exc}")
    with st.expander("Recuperar un escenario guardado"):
        recovered = st.file_uploader("Escenario guardado (.json)", type=["json"], key=key("recovered"))
        if st.button("Recuperar escenario", disabled=recovered is None):
            try:
                loaded = json.loads(recovered.getvalue())
                issues = validate(loaded)
                if issues or loaded.get("version") != 1:
                    st.error("\n\n".join(issues) or "Versión de escenario no compatible.")
                else:
                    replace_scenario(loaded)
            except Exception as exc:
                st.error(f"No se pudo recuperar: {exc}")
    if st.button("Restablecer caso Volpak 4"):
        replace_scenario(demo())
    st.markdown("#### Productos y necesidades")
    st.caption("Puedes agregar o eliminar filas. Al agregar un producto, completa también sus cambios de entrada y salida. La velocidad siempre se expresa por 8 horas, aunque configures turnos más cortos.")
    base_products = pd.DataFrame(source["products"])
    edited = st.data_editor(base_products, num_rows="dynamic", hide_index=True, width="stretch", key=key("products"), column_order=["id", "description", "demand", "rate", "line"],
        column_config={"id": st.column_config.TextColumn("Código", required=True), "description": st.column_config.TextColumn("Producto", width="large", required=True), "line": st.column_config.TextColumn("Línea", required=True), "rate": st.column_config.NumberColumn("Cartones / 8 h", min_value=0.001, required=True), "demand": st.column_config.NumberColumn("Necesidad base", min_value=0, step=1, required=True)})
    products = []
    for record in edited.to_dict("records"):
        row = {k: None if pd.isna(v) else v for k, v in record.items()}
        row["id"] = str(row["id"] or "").strip()
        products.append(row)
    ids = list(dict.fromkeys(p["id"] for p in products if p["id"]))
    with calendar_details:
        initial_options = ["Sin preparación inicial"] + ids
        initial_default = str(cfg.get("initial")) if cfg.get("initial") is not None else initial_options[0]
        initial = st.selectbox("Último producto antes del horizonte", initial_options, index=initial_options.index(initial_default) if initial_default in initial_options else 0, key=key("initial"))
        if initial == initial_options[0]:
            st.caption("Supuesto: el primer producto no consume preparación inicial. Confirma esta condición antes de usar el plan en planta.")
    with st.expander("Tiempos de cambio (minutos)", expanded=False):
        st.caption("Fila = producto que sale. Columna = producto que entra. Cero es un cambio gratuito; un blanco es un dato pendiente. Se permiten matrices asimétricas.")
        matrix_key = key("matrix_" + json.dumps(ids))
        seed_key = key("matrix_latest")
        if matrix_key + "_base" not in st.session_state:
            st.session_state[matrix_key + "_base"] = copy.deepcopy(st.session_state.get(seed_key, source["matrix"]))
        matrix_seed = st.session_state[matrix_key + "_base"]
        grid = pd.DataFrame({b: [matrix_seed.get(f"{a}|{b}", 0 if a == b else None) for a in ids] for b in ids}, index=pd.Index(ids, name="De / A"))
        mx = st.data_editor(grid, width="stretch", key=matrix_key, column_config={b: st.column_config.NumberColumn(b, min_value=0, step=0.001) for b in ids})
    with calendar_details:
        with st.expander("Paradas por turno", expanded=False):
            st.caption("Los minutos de parada se ubican al inicio del turno. Para cerrar un turno completo, registra toda su duración. Los lotes y cambios se retoman sin preparación adicional.")
            raw = pd.DataFrame(source.get("closures", []), columns=["date", "shift", "minutes"])
            raw["date"] = pd.to_datetime(raw["date"]).dt.date
            stops = st.data_editor(raw, num_rows="dynamic", hide_index=True, key=key("closures"), width="stretch", column_config={"date": st.column_config.DateColumn("Fecha", required=True), "shift": st.column_config.NumberColumn("Turno", min_value=1, max_value=3, step=1, required=True), "minutes": st.column_config.NumberColumn("Minutos de parada", min_value=0, required=True)})
    closures = []
    for r in stops.to_dict("records"):
        closures.append({"date": str(r["date"]), "shift": None if pd.isna(r["shift"]) else r["shift"], "minutes": None if pd.isna(r["minutes"]) else r["minutes"]})
    matrix = {f"{a}|{b}": None if pd.isna(mx.loc[a, b]) else float(mx.loc[a, b]) for a in ids for b in ids}
    st.session_state[seed_key] = copy.deepcopy(matrix)
    current = {"version": 1, "name": name, "products": products, "matrix": matrix, "config": {"year": selected_month.year, "month": selected_month.month, "weekday_shifts": weekday, "saturday_shifts": saturday, "sunday_shifts": sunday, "shift_hours": hours, "first_hour": first_hour, "factor": 1 + growth / 100, "initial": None if initial == initial_options[0] else initial, "time_limit": limit}, "closures": closures}
    errors = validate(current)
    for error in errors:
        st.error(error)
    st.button("Continuar al calendario →", type="primary", on_click=go_step, args=(1,))
    with calendar_actions:
        actions = st.columns(2)
        actions[0].button("← Volver a productos", on_click=go_step, args=(0,))
        run = actions[1].button("Optimizar y generar plan", type="primary", disabled=bool(errors), width="stretch")
        if errors:
            st.error("Revisa los datos antes de generar el plan: " + " · ".join(errors))
        if run:
            with st.spinner("Buscando la secuencia y asignando cartones completos a cada turno…"):
                try:
                    st.session_state.result = solve(current)
                    st.session_state.next_step = 2
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se generó un plan: {exc}")

result = st.session_state.result
stale = result is not None and result["fingerprint"] != fingerprint(current)
with tabs[2]:
    if result is None:
        st.subheader("El plan comienza con tus datos")
        st.info("Revisa los productos en el paso 1 y configura el calendario en el paso 2. Después pulsa «Optimizar y generar plan».")
        st.button("Ir al calendario", on_click=go_step, args=(1,))
    else:
        if stale:
            st.warning("Pendiente de recalcular. Los resultados que ves corresponden al escenario anterior; vuelve a optimizar para aplicar los cambios.")
        st.subheader(result["scenario"]["name"])
        opt = result["optimization"]
        st.caption(("Óptimo demostrado en tiempos de cambio" if opt["status"] == "OPTIMAL" else "Mejor solución encontrada; optimalidad no demostrada") + f" · cálculo de {opt['seconds']:.2f} s")
        k = st.columns(4)
        k[0].metric("Programados", pretty(result["produced"]))
        k[1].metric("Cambios", pretty(result["setup_minutes"] / 60, 2) + " h")
        k[2].metric("Carga", pretty(result["load_percent"], 1) + " %" if result["load_percent"] is not None else "Sin capacidad")
        k[3].metric("Pendientes", pretty(result["missing"]))
        st.caption(f"Necesidad: {pretty(result['demand'])} cartones · Capacidad neta: {pretty(result['available_minutes'] / 60, 1)} horas")
        if result["missing"]:
            st.error(f"La secuencia deja {pretty(result['missing'])} cartones pendientes en este calendario. La optimización minimiza cambios; la asignación entera puede requerir más tiempo. Revisa los pendientes o habilita capacidad.")
        elif result["finish"]:
            st.success("Necesidad cubierta. Cierre: " + datetime.fromisoformat(result["finish"]).strftime("%d/%m/%Y %H:%M") + ".")
        else:
            st.success("No hay necesidad de fabricación en este escenario.")
        st.caption("La carga incluye todos los minutos productivos y cambios requeridos. El calendario reserva además pequeños huecos para completar cartones dentro de cada turno.")
        st.markdown("#### Cronograma de fabricación")
        events = pd.DataFrame(result["events"])
        if not events.empty:
            include_idle = st.checkbox("Mostrar periodos libres", value=False)
            view = events if include_idle else events[events["type"] != "Libre"]
            if not view.empty:
                view = view.copy()
                view["start"] = pd.to_datetime(view["start"], format="ISO8601")
                view["end"] = pd.to_datetime(view["end"], format="ISO8601")
                fig = px.timeline(view, x_start="start", x_end="end", y="product", color="type", hover_data=["quantity"], labels={"product": "Producto", "type": "Actividad", "quantity": "Cartones", "start": "Inicio", "end": "Fin"}, color_discrete_map={"Producción": "#237c65", "Cambio": "#dc9b39", "Parada": "#b85854", "Libre": "#c9d3cb"}, category_orders={"product": result["route"] + ["Mantenimiento", "Sin asignación"]})
                fig.update_layout(height=max(320, 33 * (len(result["route"]) + 2)), margin=dict(l=5, r=5, t=15, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#fff", legend_title_text="", xaxis_title="Fecha y hora", yaxis_title="", font=dict(family="Arial", color="#213d32"))
                fig.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=result["route"] + ["Mantenimiento", "Sin asignación"])
                fig.update_xaxes(tickformat="%d/%m")
                st.plotly_chart(fig, width="stretch")
        subtabs = st.tabs(["Producto · turno · día", "Detalle de turnos", "Pendientes", "Verificaciones"])
        with subtabs[0]:
            details = pd.DataFrame(result["details"])
            if not details.empty:
                details["slot"] = details["date"] + " · T" + details["shift"].astype(str)
                pivot = details.pivot_table(index=["id", "description"], columns="slot", values="quantity", aggfunc="sum", fill_value=0)
                pivot = pivot.reindex(result["route"], level=0)
                pivot["TOTAL"] = pivot.sum(axis=1)
                pivot.index.names = ["Código", "Producto"]
                pivot.columns.name = "Fecha · turno"
                st.dataframe(pivot, width="stretch", height=440)
                st.caption("Las columnas muestran turnos con producción o cambio. El detalle de turnos incluye todo el calendario operativo.")
        with subtabs[1]:
            st.dataframe(pd.DataFrame(result["shifts"]).rename(columns={"date": "Fecha", "shift": "Turno", "available_minutes": "Disponibles min", "maintenance_minutes": "Parada min", "production_minutes": "Producción min", "setup_minutes": "Cambio min", "idle_minutes": "Libres min", "rounding_minutes": "Hueco por cartón min", "quantity": "Cartones"}), hide_index=True, width="stretch")
        with subtabs[2]:
            st.dataframe(pd.DataFrame([{"Código": p["id"], "Producto": p["description"], "Necesidad": p["demand"], "Programado": result["made"][p["id"]], "Pendiente": result["remaining"][p["id"]]} for p in effective_products(result["scenario"])]), hide_index=True, width="stretch")
        with subtabs[3]:
            for label, ok in result["checks"].items():
                st.write(("✓ " if ok else "✗ ") + label)
            st.write(f"Cota inferior de cambios: {pretty(opt['bound'], 3)} min. Solución: {pretty(opt['objective'], 3)} min.")
            st.write(f"Tiempo libre por cartones completos: {pretty(result['rounding_minutes'], 4)} min.")
        if not stale:
            st.download_button("Descargar plan en Excel", data=excel_export(result), file_name="Plan_fabricacion.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        else:
            st.button("Recalcula para descargar el plan actualizado", disabled=True)

with tabs[2], st.expander("Comparar resultados y guardar escenario"):
    st.subheader("Compara decisiones, conserva escenarios")
    if result is not None:
        if stale:
            st.warning("Comparación del último cálculo. Los cambios actuales todavía no se han aplicado.")
        cmp = pd.DataFrame(result["comparison"])
        fig = px.bar(cmp, x="setup_minutes", y="method", orientation="h", text="setup_minutes", labels={"setup_minutes": "Minutos de cambio", "method": ""}, color="method", color_discrete_sequence=["#237c65", "#9ba99f", "#d4af74", "#7f9b9f"])
        fig.update_layout(showlegend=False, height=280, margin=dict(l=0, r=20, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")
        st.caption("Las reglas son referencias hipotéticas. Las horas de diferencia no son ahorro observado en planta ni ahorro monetario.")
        st.dataframe(cmp.drop(columns="route").rename(columns={"method": "Método", "setup_minutes": "Cambios min", "pending": "Cartones pendientes", "finish": "Cierre"}), hide_index=True, width="stretch")
    st.markdown("#### Guardar y recuperar")
    st.download_button("Guardar escenario", json.dumps(current, ensure_ascii=False, indent=2), file_name="Escenario_fabricacion.json", mime="application/json", disabled=bool(errors))
    st.caption("Este archivo guarda los datos y condiciones actuales. Recupéralo en «Productos y demanda» y vuelve a optimizar. Es la forma de conservar escenarios al cerrar la app.")
    if st.button("Añadir último resultado a la comparación", disabled=result is None or stale):
        st.session_state.saved[result["fingerprint"]] = copy.deepcopy(result)
    saved = list(st.session_state.saved.values())
    if saved:
        st.dataframe(pd.DataFrame([{"Escenario": r["scenario"]["name"], "Necesidad": r["demand"], "Capacidad h": round(r["available_minutes"] / 60, 2), "Cambios min": r["setup_minutes"], "Pendiente": r["missing"], "Cierre": r["finish"]} for r in saved]), hide_index=True, width="stretch")
        st.caption("Esta comparación permanece durante la sesión. Descarga los escenarios para conservar sus datos.")

with tabs[2], st.expander("Cómo se calcula el plan y sus supuestos"):
    st.subheader("Qué decide el modelo")
    st.write("El motor elige una secuencia que minimiza los minutos de cambio entre productos. Modela los productos individualmente mediante un circuito con un nodo ficticio, sin autolazos. El último producto del periodo anterior determina el costo de preparación inicial cuando se conoce.")
    st.latex(r"\min \sum_{i\ne j} c_{ij} x_{ij}")
    st.write("OR-Tools CP-SAT informa si demostró optimalidad o solo encontró una solución factible dentro del tiempo disponible. La cota inferior permite evaluar la distancia al óptimo.")
    st.markdown("#### Cómo se construye el calendario")
    st.write("Con la secuencia elegida, se consumen los minutos de cambio y se asigna el máximo número de cartones completos que cabe en cada turno. Los cartones no se reparten entre turnos. Las tasas se convierten desde cartones por 8 horas, independientemente de la duración de turno elegida.")
    st.markdown("#### Alcance de esta versión")
    st.markdown("""
- Una línea por escenario y una campaña por producto, pausada durante periodos cerrados.
- Necesidad neta de fabricación en cartones, requerida al cierre del horizonte; confirmar unidades y definición con planta.
- Matriz completa de cambios en minutos, incluidos ceros explícitos. No se infieren familias ni tiempos faltantes.
- Velocidad constante y efectiva; no se descuentan otra vez pérdidas ya incluidas.
- Las paradas ocurren al inicio del turno. Lotes y preparaciones se retoman sin una limpieza adicional.
- Sin restricciones de materias primas, inventario máximo, lotes mínimos, fechas de entrega intermedias ni recursos compartidos entre líneas.
""")
    st.info("La optimalidad certificada corresponde a los tiempos de cambio. La asignación de cartones enteros es posterior; no se certifica mínimo tiempo de cierre, costo total o máximo cumplimiento cuando falta capacidad.")
    st.write("Una carga agregada inferior al 100 % no sustituye verificar el plan por turno. La app muestra los pendientes reales de la secuencia programada y no sobrecarga turnos para ocultarlos.")
    st.caption("Motor: Python + OR-Tools. Interfaz: Streamlit. Caso inicial: Volpak 4.")

st.caption("by: Sebastian Parra · Los datos se procesan en este equipo.")
