# Documentación Técnica y Memoria de Auditoría Operativa
**Proyecto:** Planificador Maestro de Fabricación y Secuenciación Óptima  
**Caso de Referencia:** Línea Volpak 4 · Septiembre 2026  
**Autor:** Sebastián Parra  
**Especialización en Gerencia de Operaciones** · Métodos Cuantitativos para la Toma de Decisiones  
**Motor de Optimización:** Google OR-Tools CP-SAT (Constraint Programming - Satisfiability)  
**Interfaz:** Streamlit Cloud (Despliegue Continuo con GitHub)  

---

## 1. Alcance y Contexto Operativo

La aplicación resuelve de forma óptima el problema de secuenciación y asignación temporal de campañas de fabricación en líneas continuas de envasado (caso base: línea Volpak 4 de doypacks), donde:
1. Se debe programar la fabricación de un catálogo de productos (17 SKUs en el caso base) dentro de un horizonte temporal finito (septiembre 2026, 74 turnos disponibles bajo régimen de Lunes a Sábado).
2. Los tiempos de cambio de referencia entre productos dependen de la secuencia (matriz asimétrica $C_{ij}$ con tiempos de 0, 120 y 180 minutos).
3. Se minimiza el tiempo total improductivo de cambio de formato, y posteriormente se genera el plan detallado de cantidades enteras de cartones por turno y día sin fraccionar cartones entre turnos.

---

## 2. Formulación Matemática Formal

El problema de secuenciación de producción con tiempos de cambio dependientes de la secuencia se formula de forma rigurosa como un **Problema del Agente Viajero (Traveling Salesperson Problem - TSP) sobre un camino abierto**, utilizando la formulación con variables de posición de **Miller-Tucker-Zemlin (MTZ)** para la eliminación estricta de subtoures.

### 2.1. Conjuntos e Índices
* $V = \{1, 2, \dots, n\}$: Conjunto de productos o familias a fabricar ($n = 17$ SKUs en caso desagregado, $n = 8$ bloques conexos en caso agrupado).
* $V_0 = \{0\} \cup V$: Conjunto extendido con el nodo ficticio $0$ (nodo origen/destino que modela que la secuencia es un camino abierto de costo cero al inicio y al final).

### 2.2. Parámetros
* $c_{ij} \ge 0$: Minutos de cambio de formato al pasar del producto $i$ al producto $j$ ($\forall i, j \in V$).
* $c_{0j} = 0$: Costo de arranque para el primer producto del mes cuando no hay preparación previa requerida (o el costo real si se conoce el último producto de agosto).
* $c_{i0} = 0$: Costo ficticio de cierre tras fabricar el último producto.
* $c_{ii} = 0$: Diagonal cero (sin costo al permanecer en el mismo producto).

### 2.3. Variables de Decisión
* $x_{ij} \in \{0, 1\}$ ($\forall i, j \in V_0, i \ne j$):  
  $$x_{ij} = \begin{cases} 1 & \text{si el producto } j \text{ se fabrica inmediatamente después del producto } i \\ 0 & \text{en caso contrario} \end{cases}$$
* $u_i \in [1, n]$ ($\forall i \in V$):  
  Variable entera de posición en la secuencia para el producto o familia $i$.

### 2.4. Función Objetivo
Minimizar el tiempo total de cambio de formato en el mes:
$$\min Z = \sum_{i \in V_0} \sum_{j \in V_0, j \ne i} c_{ij} \cdot x_{ij}$$

### 2.5. Restricciones Operativas
1. **Conservación de Salida (Cada producto tiene exactamente un sucesor):**
   $$\sum_{j \in V_0, j \ne i} x_{ij} = 1, \quad \forall i \in V_0$$

2. **Conservación de Entrada (Cada producto tiene exactamente un predecesor):**
   $$\sum_{i \in V_0, i \ne j} x_{ij} = 1, \quad \forall j \in V_0$$

3. **Prevención de Autolazos (Diagonal Cero Forzada):**
   $$x_{ii} = 0, \quad \forall i \in V_0$$

4. **Eliminación de Subtoures (Miller-Tucker-Zemlin - MTZ):**
   Para garantizar que la solución sea un único camino continuo sin circuitos desconectados:
   $$u_i - u_j + n \cdot x_{ij} \le n - 1, \quad \forall i, j \in V, i \ne j$$

---

## 3. Demostración Combinatoria de Optimalidad Global

En auditorías operativas, el evaluador puede contrastar la solución del solver frente a una **demostración analítica independiente (Cota Inferior Combinatoria)** que no depende de computadores:

1. **Detección de Componentes Conexas (Familias Tecnológicas):**  
   Al agrupar los productos cuyos tiempos de cambio mutuos son de 0 minutos ($c_{ij} = 0 \land c_{ji} = 0$), los 17 SKUs se particionan de forma determinista en exactamente **8 familias conexas** disjuntas:
   * $F_1$: Vinagre (SKU 3533)
   * $F_2$: Rosada (SKU 3643)
   * $F_3$: Napolitana (SKU 15564)
   * $F_4$: Salsas de Tomate (SKUs 5998, 15881, 16787)
   * $F_5$: Piña (SKU 6743)
   * $F_6$: Barbecue (SKU 6639)
   * $F_7$: Emulsiones / Mayonesas (SKUs 3278, 3749, 7590, 15795, 16816, 17246)
   * $F_8$: Mostazas (SKUs 3757, 3925, 6616)

2. **Cota Inferior Combinatoria Irrefutable:**
   * Cualquier secuencia que fabrique todos los productos debe visitar las 8 familias.
   * Al no existir ningún cambio de 0 minutos entre familias distintas, la secuencia debe cruzar obligatoriamente **al menos 7 veces** de una familia a otra ($8 - 1 = 7$ transiciones inter-familia).
   * La transición inter-familia más barata en toda la matriz cuesta **120 minutos**.
   * Por tanto, ninguna secuencia imaginable puede costar menos de:
     $$\text{Cota Inferior} = 7 \times 120\text{ min} = \mathbf{840\text{ minutos}} \quad (14,0\text{ horas})$$

3. **Certificación de Optimalidad:**
   * La solución alcanzada por el solver CP-SAT tiene un valor objetivo exacto de **840,0 minutos**.
   * Al coincidir el valor de la solución factible con la cota inferior combinatoria teórica ($\text{Objetivo} = \text{Cota} = 840$), **queda matemáticamente demostrado que la solución es el óptimo global irrefutable**.

---

## 4. Algoritmo de Asignación y Discretización de Turnos

Una vez obtenida la secuencia óptima de productos, el motor genera el cronograma detallado por turno aplicando las siguientes reglas:

1. **Unidades Discretas e Indivisibilidad:**
   * Las necesidades se expresan en cartones enteros.
   * La velocidad $R_i$ (cartones por turno de 8 horas) se convierte a minutos por cartón:  
     $$\tau_i = \frac{480}{R_i}\text{ min/cartón}$$
   * En cada turno $t$ con tiempo productivo disponible $T_t^{\text{disp}}$ (después de restar paradas de mantenimiento y minutos de cambio), el número máximo de cartones completos a envasar es:  
     $$Q_{it} = \left\lfloor \frac{T_t^{\text{disp}}}{\tau_i} \right\rfloor$$
   * El tiempo sobrante que no alcanza para un cartón completo se computa explícitamente como **Hueco por cartón indivisible (`rounding_minutes`)**:  
     $$T_t^{\text{hueco}} = T_t^{\text{disp}} - (Q_{it} \cdot \tau_i)$$
   * En el caso Volpak 4, la suma total de huecos en todo el mes es de solo **1,9283 minutos**, demostrando un aprovechamiento casi perfecto de la capacidad de línea.

---

## 5. Matriz de Cuadre y Auditoría Contable (6 Comprobaciones)

El planificador ejecuta y audita 6 comprobaciones de integridad matemática:

| # | Comprobación Auditada | Criterio de Aceptación | Resultado Volpak 4 |
|---|---|---|:---:|
| 1 | **Cobertura Total de Demanda** | Cartones programados $\ge$ Demanda requerida | **86.331 / 86.331 (100,0%)** ✓ |
| 2 | **Ausencia de Sobrecargas** | Minutos totales por turno $\le 480,00$ min | **0 sobrecargas** ✓ |
| 3 | **Optimalidad de Cambios** | Costo alcanzado = Cota inferior combinatoria | **840 min = 840 min** ✓ |
| 4 | **Conservación de Secuencia** | 17 productos visitados sin repetición | **17 SKUs en 1 campaña** ✓ |
| 5 | **Eliminación de Autolazos** | Celdas diagonales $x_{ii} = 0$ | **0 autolazos** ✓ |
| 6 | **Reconciliación de Tiempos** | $\sum T^{\text{prod}} + \sum T^{\text{setup}} + \sum T^{\text{hueco}} + \sum T^{\text{libre}} = 35.520$ min | **Cuadre exacto al segundo** ✓ |

---

## 6. Diccionario de Datos y Contratos de Entrada/Salida

### 6.1. Contrato de Archivos Excel de Entrada
1. **Asignación de Productos (`xlsx`):**
   * `Linea Produccion`: Identificador de máquina (ej. `Volpak 4`).
   * `Id Producto asignado`: Código numérico o alfanumérico único del SKU.
   * `Descripcion Producto asignado`: Texto identificador.
   * `Cartones/Turno`: Tasa nominal en base 8 horas ($R_i > 0$).
2. **Necesidad de Fabricación (`xlsx`):**
   * `Id Producto`: Código del SKU (debe existir en Asignación).
   * `Necesidad Fabricacion`: Entero positivo en cartones.
3. **Matriz de Tiempos de Cambio (`xlsx`):**
   * Matriz $n \times n$ con códigos en fila 1 y columna 1.
   * Diagonal estrictamente en 0.
   * Tiempos en minutos ($c_{ij} \ge 0$).

### 6.2. Contrato de Escenario Canónico (`JSON`)
```json
{
  "version": 1,
  "name": "Línea Volpak 4",
  "config": {
    "year": 2026,
    "month": 9,
    "weekday_shifts": 3,
    "saturday_shifts": 2,
    "sunday_shifts": 0,
    "shift_hours": 8,
    "first_hour": 6,
    "factor": 1.0,
    "time_limit": 15
  },
  "products": [
    {"id": "3278", "description": "SALSA MAYONESA (12DP/1/380g)", "demand": 6206, "rate": 2460, "line": "Volpak 4"}
  ],
  "matrix": {"3278|3278": 0.0, "3278|3533": 120.0},
  "closures": []
}
```

---

## 7. Matriz de Pruebas Automatizadas y QA

El repositorio cuenta con una suite de **72 pruebas automatizadas** ejecutadas con Pytest:
* `test_analytics.py` (8 pruebas): Detección de familias conexas, reducción a bloques, Pareto ABC, análisis de sensibilidad y ordenamiento de matrices.
* `test_edge_cases.py` (23 pruebas): Inmunidad a inyección regex, catálogos vacíos, escenarios monopróducto, invariantes de Hamiltonianidad y validación de celdas Excel.
* `test_engine.py` (16 pruebas): Permutaciones exhaustivas TSP, validación CP-SAT, balances de turnos y exportación.
* `test_ui_and_workflow.py` (25 pruebas): Simulación headless con `AppTest` verificando reactividad de sliders, persistencia de checklist y selects de tema visual.

---

## 8. Marco Metodológico de Escalamiento a Planta

Basado en la **Hoja 13 del modelo maestro**, clasifica los 12 requerimientos indispensables para transferir este modelo a una planta multiproducto y multilínea:

* 🔴 **Bloqueantes:** Asignación de productos compartidos en máquinas paralelas, matrices de cambio específicas por máquina, velocidades diferenciadas por línea.
* 🟡 **Alto Impacto:** Niveles de inventario inicial y stock de seguridad, fechas de entrega intermedias (fraccionamiento de lotes), reglas de alérgenos y secuencias prohibidas, calendario de paradas de mantenimiento.
* 🟢 **Refinamiento:** Costeo por turno y recargo dominical, OEE real y merma, restricciones de almacenamiento de producto terminado.
