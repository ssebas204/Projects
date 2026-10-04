# Repositorio Maestro de Proyectos — Sebastian Parra

Repositorio central estructurado por proyectos de ingeniería, analítica de operaciones, optimización heurística y evolución normativa de la calidad.

[![CI & QA Automated](https://github.com/ssebas204/Projects/actions/workflows/audit_and_docs.yml/badge.svg)](https://github.com/ssebas204/Projects/actions/workflows/audit_and_docs.yml)
[![Vercel Deployment](https://img.shields.io/badge/Vercel-Deployed-black?logo=vercel)](https://clasescalidadsebas2026.vercel.app)

---

## 📂 Directorio de Proyectos

El repositorio está organizado en carpetas independientes y autocontenidas:

```
Projects/
├── plataforma-calidad-iso-2026/   # Plataforma directiva y hub interactivo de calidad (8 módulos, 85 quizzes)
├── planificador-volpak4/          # Sistema de programación heurística de empaque horizontal (Streamlit)
├── analitica-pronosticos/         # Modelos cuantitativos de pronóstico de demanda y evaluación de error
├── arboles-decision-ml/           # Árboles de decisión interactivos para toma de decisiones bajo incertidumbre
├── .github/workflows/             # Pipelines de integración continua (CI/CD) y suites de testing
└── vercel.json                    # Configuración de enrutamiento y CDN para producción
```

---

## 🚀 Proyectos en Producción & Documentación

### 1. [Plataforma Directiva ISO 9001:2026 & Calidad de Procesos](./plataforma-calidad-iso-2026)
* **Despliegue en Vivo**: [https://clasescalidadsebas2026.vercel.app](https://clasescalidadsebas2026.vercel.app)
* **Descripción**: Plataforma interactiva de nivel maestría que sintetiza la comparativa ISO 9001:2015 vs. ISO 9001:2026, debate sobre inteligencia artificial, los 6 Gurús de la Calidad, casos Harvard (NUMMI y Virginia Mason), Anexo SL y metodología cuantitativa DMAIC.
* **Stack**: HTML5 semántico, TailwindCSS, Canvas 2D, SVG vectorial, JavaScript ES6+.

### 2. [Planificador de Fabricación Volpak 4](./planificador-volpak4)
* **Descripción**: Sistema avanzado de secuenciación y balance de línea para maquinaria Volpak 4. Minimiza paradas técnicas por cambios de formato y gestiona matrices de alérgenos y limpieza profunda.
* **Stack**: Python 3.12, Streamlit, Pandas, NumPy, Pytest (64 pruebas unitarias de QA).

### 3. [Métodos Cuantitativos & Modelos de Pronósticos](./analitica-pronosticos)
* **Despliegue en Vivo**: [https://analisispronosticos.vercel.app](https://analisispronosticos.vercel.app)
* **Descripción**: Análisis comparativo de algoritmos de pronósticos (suavización exponencial simple/doble/Holt-Winters, promedios móviles y regresiones) evaluados mediante métricas de precisión (WMAPE, MAD, MSE, FACC).
* **Stack**: Python, JSON, HTML5/JS Interactivo.

### 4. [Árboles de Decisión para Toma de Decisiones](./arboles-decision-ml)
* **Despliegue en Vivo**: [https://arboldecisionapp.vercel.app](https://arboldecisionapp.vercel.app)
* **Descripción**: Simulador probabilístico interactivo para evaluación de decisiones bajo incertidumbre, cálculo del Valor Esperado Monetario (VEM) y diagramación secuencial.
* **Stack**: HTML5, JavaScript Core, Canvas interactivo.

---

## 🔒 Estándares de Seguridad y Credenciales

* **Cero Tokens Quemados**: El repositorio no almacena credenciales, claves API ni variables `.env` en código fuente ni en historial Git.
* **Autenticación Delegada**: Toda integración remota utiliza Keychain nativo y autenticación mediante Personal Access Tokens (PAT) en el entorno seguro de desarrollo.
* **CI/CD Automatizado**: Verificación automática de pruebas con Pytest en GitHub Actions ante cada commit en la rama `main`.
