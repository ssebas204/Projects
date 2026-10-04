"""
Nucleo compartido de calculo para el caso de pronostico (usado por
build_modelos_pronostico.py -> Excel y export_dashboard_data.py -> HTML).

Metodologia de evaluacion: validacion cruzada de origen movil (rolling-origin /
time series CV, Hyndman & Athanasopoulos), NO un solo corte fijo:
  - 10 origenes de CALIBRACION (para elegir alpha/beta/gamma de suavizacion y
    el orden de SARIMA) -> minimizan el error de pronostico a h=1,2,3 fuera de
    muestra, nunca el ajuste dentro de muestra.
  - 10 origenes de EVALUACION (posteriores, sin traslape con calibracion) ->
    30 pares pronostico-real por modelo (10 origenes x horizontes 1,2,3),
    usados para reportar MAE/RMSE/MAPE y decidir que modelo es mejor.
Los hiperparametros elegidos en calibracion se reusan tal cual al reajustar
cada modelo con TODOS los datos para producir el pronostico real ago-oct 2026.
"""
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from scipy.optimize import minimize
from statsmodels.tsa.holtwinters import SimpleExpSmoothing, Holt, ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

SRC = "Caso Real Pronóstico.xlsx"
HORIZON = 3
N_EVAL = 10
N_CALIB = 10
MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

ALPHA_GRID = [0.1, 0.3, 0.5, 0.7, 0.9]
BETA_GRID = [0.0, 0.1, 0.2]
GAMMA_GRID = [0.1, 0.3, 0.5, 0.7, 0.9]
SARIMA_ORDERS = [(1, 1, 1), (0, 1, 1), (1, 1, 0), (2, 1, 1)]
SARIMA_SEAS = [(1, 1, 1, 12), (0, 1, 1, 12), (1, 0, 1, 12)]


def load():
    df = pd.read_excel(SRC, sheet_name="Hoja1")
    df.columns = ["fecha", "valor"]
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.sort_values("fecha").reset_index(drop=True)
    return df


def metrics(pairs):
    """pairs: list of (actual, forecast). Devuelve MAE, RMSE, MAPE, WAPE, F-ACC sobre esos pares."""
    a = np.array([p[0] for p in pairs], dtype=float)
    f = np.array([p[1] for p in pairs], dtype=float)
    err = a - f
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mape = float(np.mean(np.abs(err / a)) * 100)
    # WAPE (a.k.a WMAPE): pesa por el tamaño del valor real, mas robusto que MAPE
    # cuando hay meses de valor bajo. F-ACC (precision de pronostico) = 100 - WAPE.
    wape = float(np.sum(np.abs(err)) / np.sum(np.abs(a)) * 100)
    facc = 100.0 - wape
    return mae, rmse, mape, wape, facc


# ---------------------------------------------------------------------------
# Pronosticadores "flat" (sin hiperparametros): reciben el indice de origen o
# (0-based, ultimo punto de entrenamiento incluido) y devuelven h valores.
# ---------------------------------------------------------------------------
def fc_naive(vals, o, h): return [vals[o]] * h
def fc_seasonal_naive(vals, o, h): return [vals[o + k - 12] for k in range(1, h + 1)]
def fc_mean(vals, o, h): return [vals[: o + 1].mean()] * h
def fc_ma(vals, o, h, window): return [vals[o - window + 1: o + 1].mean()] * h


def fc_wma(vals, o, h, weights):
    """Promedio movil ponderado de 3 periodos: w1*Y(o-2)+w2*Y(o-1)+w3*Y(o),
    pesos del mas antiguo al mas reciente. Pronostico plano (igual para todo h),
    igual convencion que MA(3)/MA(12)."""
    w1, w2, w3 = weights
    val = w1 * vals[o - 2] + w2 * vals[o - 1] + w3 * vals[o]
    return [val] * h


def calibrate_wma(vals, calib_origins):
    """Optimiza los 3 pesos (suman 1, entre 0 y 1) minimizando el MAE de
    pronostico a h=1,2,3 en los origenes de calibracion — lo mismo que hace
    Solver en Excel (GRG/Evolutionary), aqui resuelto con scipy.optimize."""
    def objective(w):
        pairs = []
        for o in calib_origins:
            fc = fc_wma(vals, o, HORIZON, w)
            for k in range(HORIZON):
                pairs.append((vals[o + 1 + k], fc[k]))
        mae, *_ = metrics(pairs)
        return mae

    x0 = np.array([1 / 3, 1 / 3, 1 / 3])
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * 3
    res = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
                   options={"ftol": 1e-10, "maxiter": 200})
    return tuple(res.x)


def fc_regression(vals, months, o, h):
    """OLS: tendencia + 11 dummies mensuales (ref=Enero), ajustado solo con datos[0:o+1]."""
    train_t = np.arange(1, o + 2)
    train_m = months[: o + 1]
    X = np.column_stack([np.ones(o + 1), train_t] + [(train_m == m).astype(float) for m in range(2, 13)])
    beta, *_ = np.linalg.lstsq(X, vals[: o + 1], rcond=None)
    target_t = np.arange(o + 2, o + 2 + h)
    target_m = months[o + 1: o + 1 + h]
    Xf = np.column_stack([np.ones(h), target_t] + [(target_m == m).astype(float) for m in range(2, 13)])
    return list(Xf @ beta)


def fit_regression_full(vals, months, n, future_months, h):
    """Ajuste final con TODOS los datos + pronostico futuro (fuera de la serie)."""
    t = np.arange(1, n + 1)
    X = np.column_stack([np.ones(n), t] + [(months == m).astype(float) for m in range(2, 13)])
    beta, *_ = np.linalg.lstsq(X, vals, rcond=None)
    fitted = X @ beta
    ft = np.arange(n + 1, n + 1 + h)
    Xf = np.column_stack([np.ones(h), ft] + [(np.array(future_months) == m).astype(float) for m in range(2, 13)])
    forecast = Xf @ beta
    return list(fitted), list(forecast)


# ---------------------------------------------------------------------------
# Suavizacion exponencial: ajuste con parametros FIJOS (optimized=False), para
# poder elegirlos por calibracion en vez de por maxima verosimilitud interna.
# ---------------------------------------------------------------------------
def _smoothing_forecast(kind, train_vals, params, h):
    s = pd.Series(train_vals)
    if kind == "ses":
        (a,) = params
        m = SimpleExpSmoothing(s, initialization_method="estimated").fit(
            smoothing_level=a, optimized=False)
    elif kind == "holt":
        a, b = params
        m = Holt(s, initialization_method="estimated").fit(
            smoothing_level=a, smoothing_trend=b, optimized=False)
    elif kind == "hw":
        a, b, g = params
        if len(train_vals) < 24:
            return None
        m = ExponentialSmoothing(s, trend="add", seasonal="add", seasonal_periods=12,
                                  initialization_method="estimated").fit(
            smoothing_level=a, smoothing_trend=b, smoothing_seasonal=g, optimized=False)
    else:
        raise ValueError(kind)
    return m.forecast(h).values, m


def calibrate_smoothing(vals, calib_origins, kind):
    grids = {
        "ses": [(a,) for a in ALPHA_GRID],
        "holt": [(a, b) for a in ALPHA_GRID for b in BETA_GRID],
        "hw": [(a, b, g) for a in ALPHA_GRID for b in BETA_GRID for g in GAMMA_GRID],
    }[kind]
    best_params, best_mae = None, np.inf
    for params in grids:
        pairs = []
        ok = True
        for o in calib_origins:
            res = _smoothing_forecast(kind, vals[: o + 1], params, HORIZON)
            if res is None:
                ok = False
                break
            fc, _ = res
            for k in range(HORIZON):
                pairs.append((vals[o + 1 + k], fc[k]))
        if not ok:
            continue
        mae = metrics(pairs)[0]
        if mae < best_mae:
            best_mae, best_params = mae, params
    return best_params


def calibrate_sarima_order(vals, calib_end_idx):
    """Selecciona (order, seasonal_order) por menor AIC usando SOLO datos
    anteriores a la ventana de evaluacion (vals[:calib_end_idx])."""
    train = pd.Series(vals[:calib_end_idx])
    best_aic, best = np.inf, None
    for order in SARIMA_ORDERS:
        for seas in SARIMA_SEAS:
            try:
                res = SARIMAX(train, order=order, seasonal_order=seas,
                               enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
                if res.aic < best_aic:
                    best_aic, best = res.aic, (order, seas)
            except Exception:
                continue
    return best, best_aic


def compute_all():
    df = load()
    vals = df["valor"].values
    months = df["fecha"].dt.month.values
    n = len(vals)
    dates = [d.strftime("%Y-%m") for d in df["fecha"]]
    future_dates = [df["fecha"].iloc[-1] + relativedelta(months=i) for i in range(1, HORIZON + 1)]
    future_labels = [d.strftime("%Y-%m") for d in future_dates]
    future_months = [d.month for d in future_dates]

    eval_origins = list(range(n - N_EVAL - HORIZON, n - HORIZON))
    calib_origins = list(range(eval_origins[0] - N_CALIB, eval_origins[0]))
    calib_range = (dates[calib_origins[0]], dates[calib_origins[-1]])
    eval_range = (dates[eval_origins[0]], dates[eval_origins[-1]])

    # ---- calibracion (solo modelos con hiperparametros) ----
    ses_params = calibrate_smoothing(vals, calib_origins, "ses")
    holt_params = calibrate_smoothing(vals, calib_origins, "holt")
    hw_params = calibrate_smoothing(vals, calib_origins, "hw")
    sarima_order, sarima_aic = calibrate_sarima_order(vals, eval_origins[0])

    models = {}

    def eval_flat(fn, **kw):
        pairs = []
        for o in eval_origins:
            fc = fn(vals, o, HORIZON, **kw)
            for k in range(HORIZON):
                pairs.append((vals[o + 1 + k], fc[k]))
        return pairs

    def add(key, label, category, fitted, forecast, pairs, note):
        mae, rmse, mape, wape, facc = metrics(pairs)
        models[key] = {
            "label": label, "category": category,
            "fitted": [None if v is None else round(float(v), 3) for v in fitted],
            "forecast": [round(float(v), 3) for v in forecast],
            "mae": round(mae, 2), "rmse": round(rmse, 2), "mape": round(mape, 2),
            "wape": round(wape, 2), "facc": round(facc, 2), "note": note,
        }

    # 1. Informales o simplistas
    naive_fitted = [None] + [vals[i - 1] for i in range(1, n)]
    add("naive", "Naive", "Informales o Simplistas", naive_fitted, [vals[-1]] * HORIZON,
        eval_flat(fc_naive), "pronostico(t) = valor(t-1)")

    naive_est_fitted = [None] * 12 + [vals[i - 12] for i in range(12, n)]
    add("naive_est", "Naive Estacional", "Informales o Simplistas", naive_est_fitted,
        list(vals[-12: -12 + HORIZON]), eval_flat(fc_seasonal_naive),
        "pronostico(t) = valor(t-12) (mismo mes del año anterior)")

    # 2. Tendencia central
    prom_fitted = [None] + [vals[:i].mean() for i in range(1, n)]
    add("prom", "Promedio Simple", "Tendencia Central", prom_fitted, [vals.mean()] * HORIZON,
        eval_flat(fc_mean), "promedio acumulado de todos los datos anteriores")

    ma3_fitted = [None] * 3 + [vals[i - 3:i].mean() for i in range(3, n)]
    add("ma3", "Media Movil (3)", "Tendencia Central", ma3_fitted, [vals[-3:].mean()] * HORIZON,
        eval_flat(fc_ma, window=3), "promedio movil de los ultimos 3 meses")

    ma12_fitted = [None] * 12 + [vals[i - 12:i].mean() for i in range(12, n)]
    add("ma12", "Media Movil (12)", "Tendencia Central", ma12_fitted, [vals[-12:].mean()] * HORIZON,
        eval_flat(fc_ma, window=12), "promedio movil de los ultimos 12 meses")

    wma_weights = calibrate_wma(vals, calib_origins)
    w1, w2, w3 = wma_weights
    wma_fitted = [None] * 3 + [w1 * vals[i - 3] + w2 * vals[i - 2] + w3 * vals[i - 1] for i in range(3, n)]
    wma_fc = [w1 * vals[-3] + w2 * vals[-2] + w3 * vals[-1]] * HORIZON
    add("wma", "Promedio Ponderado", "Tendencia Central", wma_fitted, wma_fc,
        eval_flat(fc_wma, weights=wma_weights),
        f"pesos w1={w1:.3f}, w2={w2:.3f}, w3={w3:.3f} (mas antiguo a mas reciente; "
        f"optimizados minimizando MAE, sujeto a suma=1, calibrado {calib_range[0]} a {calib_range[1]})")
    models["wma"]["state"] = {"weights": list(wma_weights)}

    # 3. Suavizacion (parametros fijados por calibracion, no MLE)
    def eval_smoothing(kind, params):
        pairs = []
        for o in eval_origins:
            fc, _ = _smoothing_forecast(kind, vals[: o + 1], params, HORIZON)
            for k in range(HORIZON):
                pairs.append((vals[o + 1 + k], fc[k]))
        return pairs

    ses_fc, ses_model = _smoothing_forecast("ses", vals, ses_params, HORIZON)
    add("ses", "SES (Suavizacion Exponencial Simple)", "Suavizacion",
        list(ses_model.fittedvalues.values), ses_fc, eval_smoothing("ses", ses_params),
        f"alpha={ses_params[0]:.2f} (calibrado {calib_range[0]} a {calib_range[1]}, h=1..3)")
    models["ses"]["state"] = {
        "alpha": float(ses_params[0]),
        "initial_level": float(ses_model.params["initial_level"]),
    }

    holt_fc, holt_model = _smoothing_forecast("holt", vals, holt_params, HORIZON)
    add("holt", "Holt (doble)", "Suavizacion",
        list(holt_model.fittedvalues.values), holt_fc, eval_smoothing("holt", holt_params),
        f"alpha={holt_params[0]:.2f}, beta={holt_params[1]:.2f} (calibrado {calib_range[0]} a {calib_range[1]})")
    models["holt"]["state"] = {
        "alpha": float(holt_params[0]), "beta": float(holt_params[1]),
        "initial_level": float(holt_model.params["initial_level"]),
        "initial_trend": float(holt_model.params["initial_trend"]),
    }

    hw_fc, hw_model = _smoothing_forecast("hw", vals, hw_params, HORIZON)
    add("hw", "Holt-Winters (triple)", "Suavizacion",
        list(hw_model.fittedvalues.values), hw_fc, eval_smoothing("hw", hw_params),
        f"alpha={hw_params[0]:.2f}, beta={hw_params[1]:.2f}, gamma={hw_params[2]:.2f} "
        f"(calibrado {calib_range[0]} a {calib_range[1]}, estacionalidad=12)")
    models["hw"]["state"] = {
        "alpha": float(hw_params[0]), "beta": float(hw_params[1]), "gamma": float(hw_params[2]),
        "initial_level": float(hw_model.params["initial_level"]),
        "initial_trend": float(hw_model.params["initial_trend"]),
        "initial_seasons": [float(v) for v in hw_model.params["initial_seasons"]],
    }

    # 4. Regresion
    reg_fitted, reg_forecast = fit_regression_full(vals, months, n, future_months, HORIZON)
    reg_pairs = []
    for o in eval_origins:
        fc = fc_regression(vals, months, o, HORIZON)
        for k in range(HORIZON):
            reg_pairs.append((vals[o + 1 + k], fc[k]))
    add("reg", "Regresion Lineal", "Regresion", reg_fitted, reg_forecast, reg_pairs,
        "valor = b0 + b1*t + dummies mensuales (referencia=Enero)")

    # 5. ARIMA/SARIMA (orden fijado por calibracion via AIC, sin ver la ventana de evaluacion)
    order, seas = sarima_order
    sarima_pairs = []
    for o in eval_origins:
        res = SARIMAX(pd.Series(vals[: o + 1]), order=order, seasonal_order=seas,
                       enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        fc = res.get_forecast(HORIZON).predicted_mean.values
        for k in range(HORIZON):
            sarima_pairs.append((vals[o + 1 + k], fc[k]))
    res_full = SARIMAX(pd.Series(vals), order=order, seasonal_order=seas,
                        enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
    sarima_fitted = list(res_full.fittedvalues.values)
    sarima_fitted[0] = None  # artefacto de inicializacion del filtro de Kalman (d=1,D=1)
    fc_obj = res_full.get_forecast(HORIZON)
    ci = fc_obj.conf_int(alpha=0.05)
    add("sarima", "SARIMA", "ARIMA", sarima_fitted, list(fc_obj.predicted_mean.values), sarima_pairs,
        f"SARIMA{order}x{seas}, orden elegido por AIC en {dates[0]} a {dates[eval_origins[0]-1]}")
    models["sarima"]["ci_lower"] = [round(float(v), 3) for v in ci.iloc[:, 0].values]
    models["sarima"]["ci_upper"] = [round(float(v), 3) for v in ci.iloc[:, 1].values]

    best_key = min(models, key=lambda k: models[k]["mape"])

    return {
        "dates": dates, "real": [round(float(v), 3) for v in vals],
        "future_labels": future_labels, "horizon": HORIZON,
        "n_eval_origins": N_EVAL, "n_calib_origins": N_CALIB,
        "eval_range": eval_range, "calib_range": calib_range,
        "models": models, "best_model": best_key,
    }


if __name__ == "__main__":
    import json
    result = compute_all()
    print("Calibracion:", result["calib_range"], "-> Evaluacion:", result["eval_range"])
    print("Mejor modelo:", result["models"][result["best_model"]]["label"],
          result["models"][result["best_model"]]["mape"], "%")
    for k, m in result["models"].items():
        print(f"  {m['label']:32s} MAE={m['mae']:>9.2f}  RMSE={m['rmse']:>9.2f}  MAPE={m['mape']:>6.2f}%")
