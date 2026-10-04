# Planificador de Fabricación Volpak 4 — Línea de Envasado Horizontal

Sistema integral de secuenciación óptima y programación de producción para la máquina envasadora horizontal Volpak 4, diseñado para minimizar tiempos muertos por cambios de formato y alérgenos.

---

## ⚙️ Características Técnicas
* **Motor de Optimización Heurística (`engine.py`)**: Minimización de matrices de cambio de formato, lavado profundo y gestión de alérgenos.
* **Interfaz de Operaciones (`app.py`)**: Dashboard interactivo desarrollado en **Streamlit** con capacidad de simulación en vivo, escenarios personalizados y exportación de órdenes.
* **Módulo de Analítica (`analytics.py`)**: Cálculo de OEE, diagramas de Pareto de pérdidas, balance de masa y utilización horaria.
* **Suite de Pruebas de Calidad**: 64 pruebas unitarias y de estrés automatizadas (`app/tests/`) con Pytest.

---

## 🚀 Instrucciones de Ejecución Local
1. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Ejecutar la aplicación:
   ```bash
   streamlit run app/app.py
   ```
3. O bien, en macOS hacer doble clic en `Abrir_Planificador.command`.

---

## 🧪 Ejecución de Pruebas Automatizadas
```bash
pytest app/tests -v
```
