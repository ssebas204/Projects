# Correcciones del Excel y uso de la app

## Excel corregido

Se conservó el archivo original y se creó `Plan_Fabricacion_Volpak4_Sep2026_Corregido.xlsx`.

Cambios realizados:

- Se agregó la restricción de diagonal cero a las instrucciones de Solver, con una celda de control que debe ser cero. Esto impide la solución inválida de autolazos.
- Se reemplazó el redondeo de cartones por una asignación de unidades completas dentro de cada turno. La columna AB de la hoja 06 registra el tiempo que no alcanza para otro cartón. El tiempo de fin de cada campaña incorpora esa espera.
- Se eliminó la tolerancia operativa de un minuto: el control exige como máximo 480 minutos por turno. El redondeo a ocho decimales solo elimina ruido numérico.
- Se agregaron controles de productos distintos, reconciliación de tiempos, tasas y necesidades válidas, y vigencia de los grupos usados en la cota inferior.
- Se ajustaron las afirmaciones sobre recálculo y reoptimización, inventarios, utilización del 85 %, ahorro observado, número de cambios de 180 minutos y alcance de las familias.
- Se distinguió la cota superior simple de un peor recorrido realmente alcanzable.
- Se retiró la afirmación de una ejecución externa de Held-Karp no adjunta. La prueba combinatoria y el costo de la secuencia siguen siendo verificables en el libro.
- Los turnos libres o cerrados ya no muestran un producto principal. Se mejoraron las etiquetas y la visualización de pequeños tiempos libres.

### Resultado verificado

| Comprobación | Resultado |
|---|---:|
| Necesidad cubierta | 86.331 cartones |
| Productos distintos | 17 |
| Tiempo de cambios | 840 minutos |
| Turnos operativos disponibles | 74 |
| Tiempo libre por indivisibilidad de cartones | 1,9283 minutos |
| Cierre del programa original corregido | 24 de septiembre, turno operativo 60 |
| Sobrecargas superiores a 480 minutos | 0 |
| Diferencias frente al cálculo independiente producto–turno | 0 |

El cálculo independiente usa aritmética racional y se contrastó con las 1.326 celdas de cantidades del programa. Se revisaron fórmulas, errores, estructura, gráficos y las áreas modificadas. No se ejecutó el complemento nativo de Solver de Excel: su configuración corregida quedó documentada para reproducirla en Excel.

El Excel conserva el alcance de 17 productos y septiembre de 2026. Su asignación entera requiere velocidades enteras expresadas por turno de ocho horas. La app admite otras velocidades y calendarios.

## App local

Abre `Abrir_Planificador.command`, o visita **http://127.0.0.1:8501** mientras el servidor esté encendido.

1. En **Preparar datos**, edita productos, necesidades, velocidades y cambios. También puedes cargar los tres Excel con la estructura del profesor.
2. Ajusta el calendario en el panel lateral. Registra paradas por turno si corresponde.
3. Pulsa **Optimizar y generar plan**.
4. Consulta el cronograma, el programa por turno, los pendientes y los controles.
5. Descarga el programa en Excel. Guarda los datos en JSON para recuperarlos después.

Los cambios de datos marcan el resultado anterior como pendiente de recalcular. El cronograma, las cantidades y las comparaciones se actualizan al ejecutar nuevamente la optimización.

El motor trabaja sobre los productos individuales, no sobre ocho familias fijas. Puede encontrar otra secuencia igualmente óptima de 840 minutos para el caso base; eso no es una inconsistencia. La certificación se refiere al tiempo de cambios. El calendario de cartones completos se construye después y no certifica mínimo plazo total.

### Validación de la app

Pasaron 16 pruebas, incluyendo comparación con enumeración exhaustiva en problemas pequeños, ausencia de autolazos, demanda excedida, calendario sin capacidad, paradas, tasas fraccionarias, validación de entradas, exportación e interacción de la interfaz. La importación de los tres archivos originales se contrastó con el caso incluido.

### Siguiente etapa

El despliegue remoto está pendiente. Esta versión funciona en el equipo local y mantiene explícito su alcance: una línea, necesidad mensual, una campaña por producto y sin restricciones adicionales de insumos, almacenamiento o fechas intermedias.
