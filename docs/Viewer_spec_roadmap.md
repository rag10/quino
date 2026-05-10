# Viewer — Spec & Roadmap

## Estado actual (diagnóstico)

### Problemas estructurales
- `SensorPlotWidget` es un `QWidget` crudo sin barra de menú, toolbar ni estado propio.
- La ventana contenedora (`QMainWindow`) se construye inline en `main_window.py`; no hay clase `PlotWindow`.
- Los `_plot_windows` se acumulan sin limpieza al cerrar ventanas.
- No hay posibilidad de importar datos externos (solo desde la simulación activa en memoria).

### Problemas de apariencia
- Fondo negro pyqtgraph, colores de canal saturados al 100% (amarillo, rojo, verde puros).
- Sin leyenda visible en el gráfico.
- Sin labels configurables en los ejes ni título de gráfico.
- Columnas del tree poco descriptivas: `""`, `x`, `y`, `Name`, `Min`, `Max`, `+`, `x`, `""`.
- Botones Delete/Export sueltos sin toolbar ni contexto visual.
- La ventana del plot no tiene icono de aplicación.

### Problemas de robustez
- Color de canal no editable desde la UI (hardcoded en `COLOR_SET`).
- Sin cursor/crosshair interactivo.
- Sin Fit View ni Reset Zoom explícitos.
- Toda la lógica de creación y selección de sensores vive en `main_window.py`.

---

## Arquitectura objetivo

```
quino/viewer/
  __init__.py
  dataset.py        — SensorDataset + load_from_csv()
  transform.py      — ChannelTransform (sin cambios)
  exporter.py       — DataExporter (sin cambios)
  qt_widget.py      — SensorPlotWidget refactorizado
  plot_window.py    — PlotWindow(QMainWindow)  ← nuevo
```

---

## Especificación de mejoras

### 1. PlotWindow — nueva clase `plot_window.py`

`PlotWindow(QMainWindow)` encapsula todo lo que hoy se construye ad-hoc en `main_window.py`.

**Menubar:**
```
File:  Import from simulation | Import from CSV… | ─ | Export… | Close
View:  Fit View | Reset Zoom | ─ | Toggle Legend | Toggle Grid | Toggle Crosshair
```

**Toolbar** (iconos SVG del proyecto, 20×20px):
| Sección | Acción | Icono |
|---------|--------|-------|
| Importar | From simulation | `play` |
| | From CSV | `folder-open` |
| Exportar | Export selected | `content-save` |
| Vista | Fit View | `fit-view` |
| | Toggle Legend | `check-circle` |
| | Toggle Grid | `four-bar` |
| Canales | Delete selected | `delete` |

**Gestión de ciclo de vida:**
- Emite signal `window_closed` al cerrar → `main_window.py` limpia `_plot_windows`.
- Acepta `app_service: ApplicationService | None` para poder importar desde simulación activa.
- Icono de ventana: `quino_app_icon_transparent_1024.png`.

---

### 2. Paleta de colores profesional

Reemplaza los colores saturados puros por paleta Tableau-10 adaptada:

```python
COLOR_PALETTE = [
    "#1f77b4",  # azul
    "#d62728",  # rojo
    "#2ca02c",  # verde
    "#ff7f0e",  # naranja
    "#9467bd",  # violeta
    "#8c564b",  # marrón
    "#e377c2",  # rosa
    "#17becf",  # cyan
    "#7f7f7f",  # gris
    "#bcbd22",  # amarillo-verde
]
```

---

### 3. Fondo blanco en pyqtgraph

Aplicado solo al widget del plot (no global):
```python
pg_window.setBackground("#fafaf8")
pg_plot.getAxis("left").setPen(pg.mkPen("#3d3d3d"))
pg_plot.getAxis("bottom").setPen(pg.mkPen("#3d3d3d"))
pg_plot.getAxis("left").setTextPen(pg.mkPen("#3d3d3d"))
pg_plot.getAxis("bottom").setTextPen(pg.mkPen("#3d3d3d"))
```

---

### 4. Leyenda y labels de ejes

**Leyenda:** `pg_plot.addLegend(offset=(10, 10))` — se muestra/oculta con acción toolbar.
Cada canal se registra: `legend.addItem(curve, channel.name)`.

**Panel de labels** (QGroupBox debajo del árbol):
- Campo `X axis label` → `pg_plot.setLabel("bottom", text)`
- Campo `Y axis label` → `pg_plot.setLabel("left", text)`
- Campo `Title` → `pg_plot.setTitle(text)`

---

### 5. Color picker por canal

En el tree, columna 1: `QPushButton` con `background-color` CSS que abre `QColorDialog`.
Al confirmar, actualiza `channel.color`, repinta la curva y el botón.

---

### 6. Importar desde CSV externo

`dataset.load_from_csv(path: Path) -> tuple[np.ndarray, list[str], str]`:
- Detecta delimitador (`,` o `\t`).
- Primera fila = headers. Si no hay headers numéricos, los infiere.
- Nombre de la matriz = nombre del fichero sin extensión.
- Carga como nueva `MatrixItem` igual que los sensores de simulación.

---

### 7. Cursor / crosshair interactivo

```python
vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#888", style=Qt.DashLine))
hline = pg.InfiniteLine(angle=0,  movable=False, pen=pg.mkPen("#888", style=Qt.DashLine))
```
- Activo/inactivo con toggle en toolbar.
- `QLabel` de coordenadas en la barra de estado de `PlotWindow`: `t = 0.1234 s  |  y = 5.678`.

---

### 8. Tree rediseñado

Columnas:
| # | Header | Contenido |
|---|--------|-----------|
| 0 | Sensor / Canal | Nombre |
| 1 | Color | Botón color (solo canales) |
| 2 | X | Checkbox |
| 3 | Y | Checkbox |
| 4 | Min | Valor mínimo (readonly) |
| 5 | Max | Valor máximo (readonly) |
| 6 | Shift | QDoubleSpinBox |
| 7 | × Mult | QDoubleSpinBox |

Cabeceras de sensor (MatrixItem): fondo `#eef2f7`, negrita, icono de sensor.
Filas de canal: alternating rows, color swatch en col 1.

---

### 9. Fit View y Reset Zoom

- **Fit View**: `pg_plot.autoRange()` — ajusta vista a todos los datos visibles.
- **Reset Zoom**: restaura rango X a `[t_min, t_max]` del canal X activo.

---

### 10. Simplificación de `main_window.py`

`create_plot_window` se reduce a:
```python
def create_plot_window(self) -> None:
    win = PlotWindow(app_service=self.app_service, parent=self)
    win.window_closed.connect(lambda: self._plot_windows.remove(win))
    win.show()
    win.prompt_import_from_simulation()
    self._plot_windows.append(win)
```

---

## Roadmap de implementación

| # | Tarea | Archivo |
|---|-------|---------|
| 1 | Paleta + fondo blanco + grid claro | `qt_widget.py` |
| 2 | Tree rediseñado: columnas claras + color picker | `qt_widget.py` |
| 3 | Leyenda + labels de ejes + título | `qt_widget.py` |
| 4 | Crosshair + coordenadas en statusbar | `qt_widget.py` |
| 5 | Fit View / Reset Zoom | `qt_widget.py` |
| 6 | `load_from_csv` | `dataset.py` |
| 7 | `PlotWindow` con toolbar + menubar + icono | `plot_window.py` |
| 8 | Simplificar `create_plot_window` | `main_window.py` |

---

## Lo que NO cambia

- `ChannelTransform` — lógica correcta, sin cambios.
- `DataExporter` — funciona bien, sin cambios.
- Flujo de simulación y `SensorOutput` en el dominio.
- API pública de `SensorDataset.get_matrix()` / `get_matrix_names()`.
