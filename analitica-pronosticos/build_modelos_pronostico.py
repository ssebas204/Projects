"""
Genera 'Caso Real Pronostico - Modelos.xlsx' con 5 categorias de modelos de pronostico
(informales, tendencia central, suavizacion, regresion, ARIMA) para la serie mensual
de 'Caso Real Pronostico.xlsx', pronosticando ago/sep/oct 2026.

Metodologia de evaluacion (ver pronostico_core.py): validacion cruzada de origen
movil (rolling-origin), no un solo corte fijo. Los modelos simples (naive, medias
moviles, regresion) se escriben como formulas reales de Excel (auditables); SES,
Holt, Holt-Winters y SARIMA se calculan en Python (pronostico_core) y se pegan
como valores, con los hiperparametros elegidos por calibracion fuera de muestra.
"""
import re
import zipfile
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import LineChart, BarChart, Reference
from openpyxl.utils import get_column_letter

from pronostico_core import compute_all, SRC as CORE_SRC


def suppress_formula_range_warnings(path, sheet_ranges):
    """Marca ciertos rangos de celdas para que Excel NO muestre el aviso verde
    'La formula omite celdas adyacentes' (falso positivo: las medias moviles y
    el promedio acumulado excluyen el mes actual a proposito). openpyxl no
    expone esto en su API publica, asi que se inyecta el XML directamente
    (<ignoredErrors formulaRange="1">), que es lo mismo que escribe Excel al
    usar 'Ignorar error' manualmente.

    sheet_ranges: dict {nombre_de_hoja: ["C5:E55", ...]}
    """
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        workbook_xml = zin.read("xl/workbook.xml").decode("utf-8")
        rels_xml = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        contents = {n: zin.read(n) for n in names}

    name_to_rid = dict(re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="(rId\d+)"', workbook_xml))
    rid_to_target = {}
    for target, rid in re.findall(r'<Relationship[^>]*Target="([^"]+worksheets/sheet\d+\.xml)"[^>]*Id="(rId\d+)"', rels_xml):
        rid_to_target[rid] = target
    for rid, target in re.findall(r'<Relationship[^>]*Id="(rId\d+)"[^>]*Target="([^"]+worksheets/sheet\d+\.xml)"', rels_xml):
        rid_to_target[rid] = target

    for sheet_name, ranges in sheet_ranges.items():
        rid = name_to_rid[sheet_name]
        target = rid_to_target[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        xml = contents[target].decode("utf-8")
        block = "<ignoredErrors>" + "".join(
            f'<ignoredError sqref="{r}" formulaRange="1"/>' for r in ranges
        ) + "</ignoredErrors>"
        assert "<drawing " in xml, f"no se encontro <drawing> en {target}"
        xml = xml.replace("<drawing ", block + "<drawing ", 1)
        contents[target] = xml.encode("utf-8")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, contents[n])

OUT = "Caso Real Pronóstico - Modelos.xlsx"
HORIZON = 3

# ---------- estilos ----------
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="B7C6D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
NUMFMT = "#,##0.0"


def style_header(ws, row, col_start, col_end):
    for c in range(col_start, col_end + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = BORDER


def autofit(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def finalize_line_chart(chart):
    """Lineas rectas (sin spline suavizado, que distorsiona la forma real de los
    datos), eje Y anclado en cero, y leyenda ABAJO (a la derecha se monta encima
    de las lineas cuando el grafico es angosto)."""
    for s in chart.series:
        s.smooth = False
    chart.y_axis.scaling.min = 0
    chart.legend.position = "b"
    return chart


def add_individual_chart(ws, anchor, title, model_col, min_row, max_row):
    """Grafica 'real' (col 2) vs una sola columna de modelo (no necesariamente contigua)."""
    ch = LineChart()
    ch.title = title
    ch.y_axis.title = "Valor"
    real_ref = Reference(ws, min_col=2, max_col=2, min_row=min_row, max_row=max_row)
    model_ref = Reference(ws, min_col=model_col, max_col=model_col, min_row=min_row, max_row=max_row)
    ch.add_data(real_ref, titles_from_data=True)
    ch.add_data(model_ref, titles_from_data=True)
    c = Reference(ws, min_col=1, min_row=min_row + 1, max_row=max_row)
    ch.set_categories(c)
    finalize_line_chart(ch)
    ch.width, ch.height = 18, 9
    ws.add_chart(ch, anchor)
    return ch


# ---------- datos y calculos (nucleo compartido con el HTML) ----------
result = compute_all()
M = result["models"]
df = pd.read_excel(CORE_SRC, sheet_name="Hoja1")
df.columns = ["fecha", "valor"]
df["fecha"] = pd.to_datetime(df["fecha"])
df = df.sort_values("fecha").reset_index(drop=True)
n = len(df)
vals = df["valor"].values
future_dates = [df["fecha"].iloc[-1] + relativedelta(months=i) for i in range(1, HORIZON + 1)]
FORECAST_LABELS = [d.strftime("%Y-%m") for d in future_dates]

wb = Workbook()
wb.remove(wb.active)

# =====================================================================
# Hoja 0: Datos
# =====================================================================
ws = wb.create_sheet("Datos")
ws["A1"] = "Serie historica - valor mensual"
ws["A1"].font = TITLE_FONT
ws.append([])
ws.append(["fecha", "valor"])
style_header(ws, 3, 1, 2)
for _, r in df.iterrows():
    ws.append([r["fecha"].strftime("%Y-%m"), round(r["valor"], 3)])
for row in range(4, 4 + n):
    ws.cell(row=row, column=2).number_format = NUMFMT
    ws.cell(row=row, column=1).border = BORDER
    ws.cell(row=row, column=2).border = BORDER
autofit(ws, [14, 14])

chart = LineChart()
chart.title = "Serie historica"
chart.y_axis.title = "Valor"
chart.x_axis.title = "Fecha"
data = Reference(ws, min_col=2, min_row=3, max_row=3 + n)
cats = Reference(ws, min_col=1, min_row=4, max_row=3 + n)
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
chart.width, chart.height = 24, 11
finalize_line_chart(chart)
ws.add_chart(chart, "D3")

# =====================================================================
# Hoja 1: Modelos informales / simplistas (Naive, Naive Estacional)
# =====================================================================
ws1 = wb.create_sheet("1_Simplistas")
ws1["A1"] = "1. Modelos Informales o Simplistas: Naive y Naive Estacional"
ws1["A1"].font = TITLE_FONT
ws1["A2"] = ("Naive: pronostico(t) = valor(t-1).  Naive Estacional: pronostico(t) = valor(t-12) "
             "(mismo mes del año anterior).")
ws1.append([])
ws1.append(["fecha", "real", "naive", "naive_estacional"])
style_header(ws1, 4, 1, 4)

for i in range(n):
    row = 5 + i  # fila fisica real: fila1 titulo, fila2 subtitulo, fila3 blanco, fila4 encabezado
    fecha = df["fecha"].iloc[i].strftime("%Y-%m")
    real = round(df["valor"].iloc[i], 3)
    naive = None if i == 0 else f"=B{row-1}"
    naive_est = None if i < 12 else f"=B{row-12}"
    ws1.append([fecha, real, naive, naive_est])

last_row = 4 + n  # fila fisica de la ultima fila historica (jul-2026)
for i, fdate in enumerate(future_dates):
    fecha = fdate.strftime("%Y-%m")
    naive = f"=B{last_row}"  # ultimo valor real conocido, constante
    naive_est = f"=B{last_row - 11 + i}"  # mismo mes año anterior
    ws1.append([fecha, None, naive, naive_est])

for r in range(5, last_row + 1 + HORIZON):
    for c in (2, 3, 4):
        cell = ws1.cell(row=r, column=c)
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws1.cell(row=r, column=1).border = BORDER
autofit(ws1, [12, 12, 12, 16])

chart1 = LineChart()
chart1.title = "Real vs Naive vs Naive Estacional (+ pronostico ago-oct 2026)"
chart1.y_axis.title = "Valor"
data1 = Reference(ws1, min_col=2, max_col=4, min_row=4, max_row=last_row + HORIZON)
cats1 = Reference(ws1, min_col=1, min_row=5, max_row=last_row + HORIZON)
chart1.add_data(data1, titles_from_data=True)
chart1.set_categories(cats1)
chart1.width, chart1.height = 26, 12
finalize_line_chart(chart1)
ws1.add_chart(chart1, "F3")

add_individual_chart(ws1, "F30", "Real vs Naive", 3, 4, last_row + HORIZON)
add_individual_chart(ws1, "P30", "Real vs Naive Estacional", 4, 4, last_row + HORIZON)

# =====================================================================
# Hoja 2: Tendencia central (Promedio simple, MA3, MA12)
# =====================================================================
ws2 = wb.create_sheet("2_Tendencia_Central")
ws2["A1"] = "2. Modelos de Tendencia Central: Promedio Simple y Medias Moviles"
ws2["A1"].font = TITLE_FONT
ws2["A2"] = ("Promedio simple acumulado hasta t-1; Media movil de 3 y 12 periodos; Promedio "
             "Ponderado de 3 periodos con pesos optimizados (ver fila 80).")
ws2.append([])
ws2.append(["fecha", "real", "promedio_simple", "ma_3", "ma_12", "promedio_ponderado"])
style_header(ws2, 4, 1, 6)

WMA_W1, WMA_W2, WMA_W3 = "$B$81", "$B$82", "$B$83"

for i in range(n):
    row = 5 + i
    fecha = df["fecha"].iloc[i].strftime("%Y-%m")
    real = round(df["valor"].iloc[i], 3)
    prom = f"=AVERAGE($B$5:B{row-1})" if i >= 1 else None
    ma3 = f"=AVERAGE(B{row-3}:B{row-1})" if i >= 3 else None
    ma12 = f"=AVERAGE(B{row-12}:B{row-1})" if i >= 12 else None
    wma = (f"={WMA_W1}*B{row-3}+{WMA_W2}*B{row-2}+{WMA_W3}*B{row-1}" if i >= 3 else None)
    ws2.append([fecha, real, prom, ma3, ma12, wma])

last_row2 = 4 + n
for i, fdate in enumerate(future_dates):
    fecha = fdate.strftime("%Y-%m")
    prom = f"=AVERAGE($B$5:$B{last_row2})"
    # Pronostico plano: promedio de las ultimas k observaciones REALES conocidas
    # (mismo valor para los 3 meses; evita referenciar celdas de pronostico en blanco).
    ma3 = f"=AVERAGE(B{last_row2-2}:B{last_row2})"
    ma12 = f"=AVERAGE(B{last_row2-11}:B{last_row2})"
    wma = f"={WMA_W1}*B{last_row2-2}+{WMA_W2}*B{last_row2-1}+{WMA_W3}*B{last_row2}"
    ws2.append([fecha, None, prom, ma3, ma12, wma])

for r in range(5, last_row2 + 1 + HORIZON):
    for c in (2, 3, 4, 5, 6):
        cell = ws2.cell(row=r, column=c)
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws2.cell(row=r, column=1).border = BORDER
autofit(ws2, [12, 12, 16, 12, 12, 16])

chart2 = LineChart()
chart2.title = "Real vs Promedio Simple vs MA(3) vs MA(12) vs Promedio Ponderado"
data2 = Reference(ws2, min_col=2, max_col=6, min_row=4, max_row=last_row2 + HORIZON)
cats2 = Reference(ws2, min_col=1, min_row=5, max_row=last_row2 + HORIZON)
chart2.add_data(data2, titles_from_data=True)
chart2.set_categories(cats2)
chart2.width, chart2.height = 26, 12
finalize_line_chart(chart2)
ws2.add_chart(chart2, "G3")

add_individual_chart(ws2, "G30", "Real vs Promedio Simple", 3, 4, last_row2 + HORIZON)
add_individual_chart(ws2, "Q30", "Real vs Media Movil (3)", 4, 4, last_row2 + HORIZON)
add_individual_chart(ws2, "G54", "Real vs Media Movil (12)", 5, 4, last_row2 + HORIZON)
add_individual_chart(ws2, "Q54", "Real vs Promedio Ponderado", 6, 4, last_row2 + HORIZON)

wma_state = M["wma"]["state"]
ws2.cell(row=80, column=1,
         value="Pesos Promedio Ponderado (optimizados minimizando MAE, restriccion suma=1)").font = BOLD
for idx, (label, value) in enumerate([
    ("w1 (mes mas antiguo, t-3)", wma_state["weights"][0]),
    ("w2 (t-2)", wma_state["weights"][1]),
    ("w3 (mes mas reciente, t-1)", wma_state["weights"][2]),
]):
    ws2.cell(row=81 + idx, column=1, value=label)
    ws2.cell(row=81 + idx, column=2, value=round(float(value), 6))

# =====================================================================
# Hoja 3: Suavizacion (SES, Holt, Holt-Winters) — formulas recursivas reales
# =====================================================================
ws3 = wb.create_sheet("3_Suavizacion")
ws3["A1"] = "3. Modelos de Suavizacion: SES, Holt y Holt-Winters"
ws3["A1"].font = TITLE_FONT
ws3["A2"] = (f"SES: {M['ses']['note']} | Holt: {M['holt']['note']} | "
             f"Holt-Winters: {M['hw']['note']}. Parametros elegidos por calibracion "
             "(no por maxima verosimilitud sobre todos los datos). Formulas recursivas "
             "auditables desde la fila 80: nivel, tendencia y estacionalidad de cada modelo.")
ws3.append([])
ws3.append(["fecha", "real", "ses", "holt", "holt_winters"])
style_header(ws3, 4, 1, 5)

for i in range(n):
    fecha = df["fecha"].iloc[i].strftime("%Y-%m")
    ws3.append([fecha, round(float(vals[i]), 3), None, None, None])
last_row3 = 4 + n
for i, fdate in enumerate(future_dates):
    ws3.append([fdate.strftime("%Y-%m"), None, None, None, None])

for r in range(5, last_row3 + 1 + HORIZON):
    for c in (2, 3, 4, 5):
        cell = ws3.cell(row=r, column=c)
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws3.cell(row=r, column=1).border = BORDER
autofit(ws3, [12, 12, 12, 12, 14])

chart3 = LineChart()
chart3.title = "Real vs SES vs Holt vs Holt-Winters"
data3 = Reference(ws3, min_col=2, max_col=5, min_row=4, max_row=last_row3 + HORIZON)
cats3 = Reference(ws3, min_col=1, min_row=5, max_row=last_row3 + HORIZON)
chart3.add_data(data3, titles_from_data=True)
chart3.set_categories(cats3)
chart3.width, chart3.height = 26, 12
finalize_line_chart(chart3)
ws3.add_chart(chart3, "G3")

add_individual_chart(ws3, "G30", "Real vs SES", 3, 4, last_row3 + HORIZON)
add_individual_chart(ws3, "Q30", "Real vs Holt", 4, 4, last_row3 + HORIZON)
add_individual_chart(ws3, "G54", "Real vs Holt-Winters", 5, 4, last_row3 + HORIZON)

# ---------------------------------------------------------------------------
# Estado interno recursivo de SES/Holt/Holt-Winters, escrito como formulas
# reales (verificado contra statsmodels: maxima diferencia < 1e-9).
#   Nivel:        L_t = alpha*Y_t + (1-alpha)*(L_(t-1) [+T_(t-1)])
#   Tendencia:    T_t = beta*(L_t-L_(t-1)) + (1-beta)*T_(t-1)
#   Estacional:   S_t = gamma*(Y_t-L_(t-1)-T_(t-1)) + (1-gamma)*S_(t-12)
#   Ajustado_t (un paso adelante) = L_(t-1) [+T_(t-1)] [+S_(t-12)]
# k=0 es el instante ANTES de la primera observacion (nivel/tendencia/
# estacional iniciales, tal como los estimo statsmodels).
# ---------------------------------------------------------------------------
ses_state, holt_state, hw_state = M["ses"]["state"], M["holt"]["state"], M["hw"]["state"]

PARAM_ROW0 = 80
ws3.cell(row=PARAM_ROW0, column=1,
         value="Parametros y estado inicial (para auditar SES / Holt / Holt-Winters)").font = BOLD
param_rows = [
    ("SES alpha", ses_state["alpha"]),
    ("SES nivel inicial (L0)", ses_state["initial_level"]),
    ("Holt alpha", holt_state["alpha"]),
    ("Holt beta", holt_state["beta"]),
    ("Holt nivel inicial (L0)", holt_state["initial_level"]),
    ("Holt tendencia inicial (T0)", holt_state["initial_trend"]),
    ("HW alpha", hw_state["alpha"]),
    ("HW beta", hw_state["beta"]),
    ("HW gamma", hw_state["gamma"]),
    ("HW nivel inicial (L0)", hw_state["initial_level"]),
    ("HW tendencia inicial (T0)", hw_state["initial_trend"]),
]
for idx, (label, value) in enumerate(param_rows):
    row = PARAM_ROW0 + 1 + idx
    ws3.cell(row=row, column=1, value=label)
    ws3.cell(row=row, column=2, value=round(float(value), 6))

SES_ALPHA, SES_L0 = f"$B${PARAM_ROW0+1}", f"$B${PARAM_ROW0+2}"
HOLT_ALPHA, HOLT_BETA = f"$B${PARAM_ROW0+3}", f"$B${PARAM_ROW0+4}"
HOLT_L0, HOLT_T0 = f"$B${PARAM_ROW0+5}", f"$B${PARAM_ROW0+6}"
HW_ALPHA, HW_BETA, HW_GAMMA = f"$B${PARAM_ROW0+7}", f"$B${PARAM_ROW0+8}", f"$B${PARAM_ROW0+9}"
HW_L0, HW_T0 = f"$B${PARAM_ROW0+10}", f"$B${PARAM_ROW0+11}"

STATE_HEADER_ROW = PARAM_ROW0 + 14
STATE_START = STATE_HEADER_ROW + 1  # fila de k=0
K_MAX = n + HORIZON - 1  # solo hasta donde el pronostico a 3 meses necesita el rezago estacional

ws3.cell(row=STATE_HEADER_ROW, column=1, value="Estacional inicial HW (S0)").font = BOLD
ws3.cell(row=STATE_HEADER_ROW, column=4,
         value="Estado interno (k=0 = antes de la primera observacion)").font = BOLD
for col, label in [(1, "mes rel."), (2, "valor S0"), (4, "k"), (5, "L_ses"),
                    (6, "L_holt"), (7, "T_holt"), (8, "L_hw"), (9, "T_hw"), (10, "S_hw")]:
    c = ws3.cell(row=STATE_HEADER_ROW + 1, column=col, value=label)
    c.font = BOLD

for k in range(K_MAX + 1):
    row = STATE_START + k
    ws3.cell(row=row, column=4, value=k)
    if k <= 11:
        ws3.cell(row=row, column=1, value=k + 1)
        ws3.cell(row=row, column=2, value=round(float(hw_state["initial_seasons"][k]), 6))
        ws3.cell(row=row, column=10, value=f"=B{row}")
    if k == 0:
        ws3.cell(row=row, column=5, value=f"={SES_L0}")
        ws3.cell(row=row, column=6, value=f"={HOLT_L0}")
        ws3.cell(row=row, column=7, value=f"={HOLT_T0}")
        ws3.cell(row=row, column=8, value=f"={HW_L0}")
        ws3.cell(row=row, column=9, value=f"={HW_T0}")
    elif k <= n:
        t = k - 1  # periodo (0-based) que se acaba de observar
        main_row = 5 + t
        prev = row - 1
        ws3.cell(row=row, column=5, value=f"={SES_ALPHA}*B{main_row}+(1-{SES_ALPHA})*E{prev}")
        ws3.cell(row=row, column=6, value=f"={HOLT_ALPHA}*B{main_row}+(1-{HOLT_ALPHA})*(F{prev}+G{prev})")
        ws3.cell(row=row, column=7, value=f"={HOLT_BETA}*(F{row}-F{prev})+(1-{HOLT_BETA})*G{prev}")
        ws3.cell(row=row, column=8, value=f"={HW_ALPHA}*(B{main_row}-J{prev})+(1-{HW_ALPHA})*(H{prev}+I{prev})")
        ws3.cell(row=row, column=9, value=f"={HW_BETA}*(H{row}-H{prev})+(1-{HW_BETA})*I{prev}")
    if k >= 12:
        t = k - 12  # periodo cuyo componente estacional se esta actualizando (rezago de 12)
        main_row = 5 + t
        state_row_t = STATE_START + t  # fila k=t: contiene L_(t-1), T_(t-1)
        ws3.cell(row=row, column=10,
                 value=f"={HW_GAMMA}*(B{main_row}-H{state_row_t}-I{state_row_t})+(1-{HW_GAMMA})*J{state_row_t}")
    for c in (2, 5, 6, 7, 8, 9, 10):
        ws3.cell(row=row, column=c).number_format = NUMFMT

# Formulas de la tabla principal (fitted historico + pronostico), leyendo el estado
for i in range(n):
    main_row = 5 + i
    state_row = STATE_START + i
    ws3.cell(row=main_row, column=3, value=f"=E{state_row}")
    ws3.cell(row=main_row, column=4, value=f"=F{state_row}+G{state_row}")
    ws3.cell(row=main_row, column=5, value=f"=H{state_row}+I{state_row}+J{state_row}")
final_state_row = STATE_START + n
for h, fdate in enumerate(future_dates, start=1):
    main_row = last_row3 + h
    lag_row = STATE_START + (n + h - 1)
    ws3.cell(row=main_row, column=3, value=f"=E{final_state_row}")
    ws3.cell(row=main_row, column=4, value=f"=F{final_state_row}+{h}*G{final_state_row}")
    ws3.cell(row=main_row, column=5, value=f"=H{final_state_row}+{h}*I{final_state_row}+J{lag_row}")

# =====================================================================
# Hoja 4: Regresion lineal (tendencia + estacionalidad por mes)
# =====================================================================
month_names = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
months = df["fecha"].dt.month.values
X_t = np.arange(1, n + 1)
X = np.column_stack([np.ones(n), X_t] + [(months == m).astype(float) for m in range(2, 13)])
beta, *_ = np.linalg.lstsq(X, vals, rcond=None)

ws4 = wb.create_sheet("4_Regresion")
ws4["A1"] = "4. Modelo de Regresion Lineal (tendencia + estacionalidad mensual)"
ws4["A1"].font = TITLE_FONT
ws4["A2"] = "valor = b0 + b1*t + suma(bm*mes_m), mes de referencia = Enero. Coeficientes:"
ws4.append([])
coef_row = 4
ws4.cell(row=coef_row, column=1, value="Intercepto (Ene)")
ws4.cell(row=coef_row, column=2, value=round(float(beta[0]), 4))
ws4.cell(row=coef_row + 1, column=1, value="Tendencia (t)")
ws4.cell(row=coef_row + 1, column=2, value=round(float(beta[1]), 4))
for idx, mname in enumerate(month_names[1:], start=0):
    ws4.cell(row=coef_row + 2 + idx, column=1, value=f"Dummy {mname}")
    ws4.cell(row=coef_row + 2 + idx, column=2, value=round(float(beta[2 + idx]), 4))

data_start_col = 4
date_col = get_column_letter(data_start_col)  # "D": fecha de cada fila (usada dentro de la formula)
ws4.cell(row=3, column=data_start_col, value="fecha")
ws4.cell(row=3, column=data_start_col + 1, value="real")
ws4.cell(row=3, column=data_start_col + 2, value="regresion")
style_header(ws4, 3, data_start_col, data_start_col + 2)


def regresion_formula(r, t):
    """valor = intercepto + tendencia*t + dummy del mes (0 si es enero).
    El mes se extrae del texto de fecha (AAAA-MM) en la propia fila."""
    mes = f"VALUE(MID({date_col}{r},6,2))"
    return f"=$B$4+$B$5*{t}+IF({mes}=1,0,INDEX($B$6:$B$16,{mes}-1))"


for i in range(n):
    r = 4 + i
    ws4.cell(row=r, column=data_start_col, value=df["fecha"].iloc[i].strftime("%Y-%m"))
    ws4.cell(row=r, column=data_start_col + 1, value=round(float(vals[i]), 3))
    ws4.cell(row=r, column=data_start_col + 2, value=regresion_formula(r, i + 1))
last_row4 = 3 + n
for i, fdate in enumerate(future_dates):
    r = last_row4 + 1 + i
    ws4.cell(row=r, column=data_start_col, value=fdate.strftime("%Y-%m"))
    ws4.cell(row=r, column=data_start_col + 2, value=regresion_formula(r, n + 1 + i))

for r in range(4, last_row4 + 1 + HORIZON):
    for c in (data_start_col + 1, data_start_col + 2):
        cell = ws4.cell(row=r, column=c)
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws4.cell(row=r, column=data_start_col).border = BORDER
autofit(ws4, [18, 12, 4, 12, 12, 12])

chart4 = LineChart()
chart4.title = "Real vs Regresion (tendencia + estacionalidad)"
data4 = Reference(ws4, min_col=data_start_col + 1, max_col=data_start_col + 2, min_row=3,
                   max_row=last_row4 + HORIZON)
cats4 = Reference(ws4, min_col=data_start_col, min_row=4, max_row=last_row4 + HORIZON)
chart4.add_data(data4, titles_from_data=True)
chart4.set_categories(cats4)
chart4.width, chart4.height = 26, 12
finalize_line_chart(chart4)
ws4.add_chart(chart4, "H3")

# =====================================================================
# Hoja 5: ARIMA (SARIMA estacional) — valores de pronostico_core
# =====================================================================
ws5 = wb.create_sheet("5_ARIMA")
ws5["A1"] = "5. Modelo ARIMA/SARIMA"
ws5["A1"].font = TITLE_FONT
ws5["A2"] = (f"{M['sarima']['note']}. Ajustado en Python (statsmodels); valores e intervalo "
             "de confianza 95% pegados.")
ws5.append([])
ws5.append(["fecha", "real", "ajustado", "pronostico", "ic_inferior", "ic_superior"])
style_header(ws5, 4, 1, 6)

sarima_fitted = M["sarima"]["fitted"]
for i in range(n):
    ws5.append([df["fecha"].iloc[i].strftime("%Y-%m"), round(float(vals[i]), 3),
                sarima_fitted[i], None, None, None])
last_row5 = 4 + n
for i, fdate in enumerate(future_dates):
    ws5.append([fdate.strftime("%Y-%m"), None, None, M["sarima"]["forecast"][i],
                M["sarima"]["ci_lower"][i], M["sarima"]["ci_upper"][i]])

for r in range(5, last_row5 + 1 + HORIZON):
    for c in (2, 3, 4, 5, 6):
        cell = ws5.cell(row=r, column=c)
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws5.cell(row=r, column=1).border = BORDER
autofit(ws5, [12, 12, 12, 12, 12, 12])

chart5 = LineChart()
chart5.title = "Real vs Ajustado vs Pronostico SARIMA (IC 95%)"
data5 = Reference(ws5, min_col=2, max_col=6, min_row=4, max_row=last_row5 + HORIZON)
cats5 = Reference(ws5, min_col=1, min_row=5, max_row=last_row5 + HORIZON)
chart5.add_data(data5, titles_from_data=True)
chart5.set_categories(cats5)
chart5.width, chart5.height = 26, 12
finalize_line_chart(chart5)
ws5.add_chart(chart5, "H3")

# =====================================================================
# Hoja 6: Resumen comparativo
# =====================================================================
ws6 = wb.create_sheet("Resumen_Comparativo")
ws6["A1"] = "Resumen Comparativo de Modelos"
ws6["A1"].font = TITLE_FONT
ws6["A2"] = (f"Validacion cruzada de origen movil: 10 origenes de evaluacion "
             f"({result['eval_range'][0]} a {result['eval_range'][1]}), pronosticando h=1,2,3 meses "
             f"(30 pares pronostico-real por modelo). Hiperparametros de SES/Holt/Holt-Winters/SARIMA "
             f"calibrados aparte, en 10 origenes previos ({result['calib_range'][0]} a "
             f"{result['calib_range'][1]}), minimizando error de pronostico fuera de muestra.")

model_order = ["naive", "naive_est", "prom", "ma3", "ma12", "wma", "ses", "holt", "hw", "reg", "sarima"]
model_names = [M[k]["label"] for k in model_order]
mae_list = [M[k]["mae"] for k in model_order]
rmse_list = [M[k]["rmse"] for k in model_order]
mape_list = [M[k]["mape"] for k in model_order]
wape_list = [M[k]["wape"] for k in model_order]
facc_list = [M[k]["facc"] for k in model_order]

ws6.append([])
ws6.append(["Modelo", "MAE", "RMSE", "MAPE (%)", "WAPE (%)", "F-ACC (%)"])
style_header(ws6, 4, 1, 6)
for name, mae_v, rmse_v, mape_v, wape_v, facc_v in zip(
        model_names, mae_list, rmse_list, mape_list, wape_list, facc_list):
    ws6.append([name, round(mae_v, 2), round(rmse_v, 2), round(mape_v, 2), round(wape_v, 2), round(facc_v, 2)])
metrics_last_row = 4 + len(model_names)
for r in range(5, metrics_last_row + 1):
    for c in (2, 3, 4, 5, 6):
        cell = ws6.cell(row=r, column=c)
        cell.number_format = "#,##0.00"
        cell.border = BORDER
    ws6.cell(row=r, column=1).border = BORDER
best_idx = int(np.argmin(mape_list))
ws6.cell(row=5 + best_idx, column=1).font = BOLD
ws6.cell(row=5 + best_idx, column=4).font = BOLD
ws6.cell(row=5 + best_idx, column=5).font = BOLD
ws6.cell(row=5 + best_idx, column=6).font = BOLD

barchart = BarChart()
barchart.title = "MAPE (%) por modelo - menor es mejor"
barchart.type = "col"
bdata = Reference(ws6, min_col=4, min_row=4, max_row=metrics_last_row)
bcats = Reference(ws6, min_col=1, min_row=5, max_row=metrics_last_row)
barchart.add_data(bdata, titles_from_data=True)
barchart.set_categories(bcats)
barchart.width, barchart.height = 22, 11
ws6.add_chart(barchart, "H4")

# Fuente (hoja, columna, primera fila de pronostico) de cada modelo, para que esta
# tabla y la de mas abajo REFERENCIEN las celdas de su hoja de detalle en vez de
# pegar el numero (todas las hojas, salvo SARIMA, ya tienen formula en esa celda).
FORECAST_SOURCE = {
    "naive": ("1_Simplistas", 3, last_row + 1),
    "naive_est": ("1_Simplistas", 4, last_row + 1),
    "prom": ("2_Tendencia_Central", 3, last_row2 + 1),
    "ma3": ("2_Tendencia_Central", 4, last_row2 + 1),
    "ma12": ("2_Tendencia_Central", 5, last_row2 + 1),
    "wma": ("2_Tendencia_Central", 6, last_row2 + 1),
    "ses": ("3_Suavizacion", 3, last_row3 + 1),
    "holt": ("3_Suavizacion", 4, last_row3 + 1),
    "hw": ("3_Suavizacion", 5, last_row3 + 1),
    "reg": ("4_Regresion", data_start_col + 2, last_row4 + 1),
    "sarima": ("5_ARIMA", 4, last_row5 + 1),
}


def forecast_ref(model_key, h_idx):
    """Formula que apunta a la celda de pronostico (h=h_idx, 0-based) de un modelo."""
    sheet, col, first_row = FORECAST_SOURCE[model_key]
    return f"='{sheet}'!{get_column_letter(col)}{first_row + h_idx}"


fc_start_row = metrics_last_row + 3
ws6.cell(row=fc_start_row, column=1, value="Pronostico Ago-Sep-Oct 2026 por modelo").font = BOLD
ws6.append([])
header_row = fc_start_row + 2
ws6.cell(row=header_row, column=1, value="Modelo")
for i, lab in enumerate(FORECAST_LABELS):
    ws6.cell(row=header_row, column=2 + i, value=lab)
style_header(ws6, header_row, 1, 1 + HORIZON)

for i, key in enumerate(model_order):
    r = header_row + 1 + i
    ws6.cell(row=r, column=1, value=model_names[i])
    for j in range(HORIZON):
        cell = ws6.cell(row=r, column=2 + j, value=forecast_ref(key, j))
        cell.number_format = NUMFMT
        cell.border = BORDER
    ws6.cell(row=r, column=1).border = BORDER
fc_last_row = header_row + len(model_names)
autofit(ws6, [18, 12, 12, 12, 12, 12])

# Tabla auxiliar para el grafico final: historico (ultimos 12m) + pronosticos de cada modelo
hist_chart_row = fc_last_row + 3
ws6.cell(row=hist_chart_row, column=1, value="Historico reciente + pronosticos (grafico)").font = BOLD
hist_header_row = hist_chart_row + 1
cols_hdr = ["fecha", "real"] + model_names
for j, h in enumerate(cols_hdr, start=1):
    ws6.cell(row=hist_header_row, column=j, value=h)
style_header(ws6, hist_header_row, 1, len(cols_hdr))

recent = df.iloc[-12:].reset_index(drop=True)
first_data_row = hist_header_row + 1
for i in range(len(recent)):
    r = first_data_row + i
    ws6.cell(row=r, column=1, value=recent["fecha"].iloc[i].strftime("%Y-%m"))
    ws6.cell(row=r, column=2, value=round(float(recent["valor"].iloc[i]), 3)).number_format = NUMFMT
last_hist_row = first_data_row + len(recent) - 1
for i, fdate in enumerate(future_dates):
    r = last_hist_row + 1 + i
    ws6.cell(row=r, column=1, value=fdate.strftime("%Y-%m"))
    for k, key in enumerate(model_order):
        cell = ws6.cell(row=r, column=3 + k, value=forecast_ref(key, i))
        cell.number_format = NUMFMT
last_combo_row = last_hist_row + HORIZON
for r in range(first_data_row, last_combo_row + 1):
    for c in range(1, len(cols_hdr) + 1):
        ws6.cell(row=r, column=c).border = BORDER

finalchart = LineChart()
finalchart.title = "Historico reciente vs pronosticos de los 5 modelos (ago-oct 2026)"
fdata = Reference(ws6, min_col=2, max_col=2 + len(model_names), min_row=hist_header_row,
                   max_row=last_combo_row)
fcats = Reference(ws6, min_col=1, min_row=first_data_row, max_row=last_combo_row)
finalchart.add_data(fdata, titles_from_data=True)
finalchart.set_categories(fcats)
finalchart.width, finalchart.height = 32, 15
finalize_line_chart(finalchart)
for s in finalchart.series:
    s.marker.symbol = "circle"
    s.marker.size = 5
ws6.add_chart(finalchart, "F" + str(hist_chart_row))

# Graficas individuales por modelo (real reciente vs pronostico de cada modelo por separado)
grid_start_row = last_combo_row + 32
grid_label_row = grid_start_row - 1
ws6.cell(row=grid_label_row, column=1, value="Pronostico por modelo (graficas individuales)").font = BOLD
anchor_cols = ["A", "K"]
for idx, name in enumerate(model_names):
    col_letter = anchor_cols[idx % 2]
    row_num = grid_start_row + (idx // 2) * 18
    ch = LineChart()
    ch.title = f"Real vs {name}"
    ch.y_axis.title = "Valor"
    real_ref = Reference(ws6, min_col=2, max_col=2, min_row=hist_header_row, max_row=last_combo_row)
    model_ref = Reference(ws6, min_col=3 + idx, max_col=3 + idx, min_row=hist_header_row, max_row=last_combo_row)
    ch.add_data(real_ref, titles_from_data=True)
    ch.add_data(model_ref, titles_from_data=True)
    cats_ind = Reference(ws6, min_col=1, min_row=first_data_row, max_row=last_combo_row)
    ch.set_categories(cats_ind)
    finalize_line_chart(ch)
    ch.width, ch.height = 16, 8
    ws6.add_chart(ch, f"{col_letter}{row_num}")

wb.save(OUT)

# Las formulas de naive/naive_estacional y de los promedios/medias moviles excluyen
# a proposito el mes actual (son pronosticos "un paso adelante"), lo que Excel
# confunde con una fila u omitida por error. Se suprime ese aviso puntualmente.
suppress_formula_range_warnings(OUT, {
    "1_Simplistas": [f"C5:D{last_row + HORIZON}"],
    "2_Tendencia_Central": [f"C5:E{last_row2 + HORIZON}"],
})

print("OK ->", OUT)
print("Calibracion:", result["calib_range"], "-> Evaluacion:", result["eval_range"])
print("Mejor modelo por MAPE:", model_names[best_idx], round(mape_list[best_idx], 2), "%")
