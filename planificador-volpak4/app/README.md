# Manufactura · Planificador local

Aplicación en Python para programar una línea de fabricación. Incluye Volpak 4 como ejemplo editable y acepta otros productos, matrices y meses.

## Abrir

En este equipo, abre `Abrir_Planificador.command` en la carpeta superior. La app se sirve en **http://127.0.0.1:8501**. Si cierras el proceso de la terminal, se detiene el servidor.

En otro equipo con Python 3.12 o superior:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Uso

1. Edita productos, cantidades, velocidades y matriz o importa los tres Excel del profesor.
2. Configura mes, turnos, producto inicial y paradas.
3. Pulsa **Optimizar y generar plan**.
4. Consulta cronograma, cantidades por turno, pendientes y verificaciones.
5. Descarga el plan en Excel y el escenario en JSON. Recupera el JSON para continuar otro día.

Los cambios marcan los resultados anteriores como pendientes de recalcular. El JSON conserva los datos; las comparaciones guardadas en memoria duran la sesión.

## Definiciones y alcance

- Una línea por escenario, hasta 80 productos, sin asignación entre máquinas.
- Necesidad neta en cartones enteros. El factor de escenario redondea cada necesidad hacia arriba.
- Velocidad en cartones por **8 horas**, aunque el turno tenga otra duración.
- Cambios en minutos con hasta tres decimales. Fila = origen y columna = destino. La diagonal debe ser cero. No se sustituyen blancos fuera de la diagonal.
- Una campaña por producto con necesidad positiva. Las campañas y cambios pueden pausarse y retomarse sin costo adicional.
- Las paradas se colocan al inicio del turno. La fecha del turno es la del día operativo; un turno puede finalizar al día siguiente.
- Se minimiza tiempo de cambios con CP-SAT. La asignación de cantidades enteras al calendario ocurre después; no se certifica mínimo plazo total.
- No se incluyen restricciones de insumos, alérgenos, lotes mínimos, almacenamiento o fechas intermedias.
- Una solución con pendientes no se presenta como un plan completo. La optimalidad mostrada se refiere solo a los cambios.

## Verificación

```sh
python -m pip install pytest
python -m pytest tests -q
```

El conjunto de pruebas compara la optimización con enumeración exhaustiva en problemas pequeños y verifica capacidades, cantidades, paradas, escenarios sin capacidad, importación, exportación y el caso base.

## Despliegue posterior

Esta entrega se ejecuta únicamente en localhost. No publica datos ni crea un servicio remoto. El código y las dependencias están separados para preparar un despliegue posterior. Antes de publicar se elegirá el alojamiento, el acceso a la app y qué datos de demostración incluir.

Documentación: [Streamlit](https://docs.streamlit.io/) y [OR-Tools CP-SAT](https://developers.google.com/optimization/cp).
