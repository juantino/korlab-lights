# KorLab Lights — Propuestas de diseño moderno (agent-ready)

Archivo a modificar: `~/korlab-lights/preview-escenas.html` (self-contained, sin build).
Cada propuesta es independiente e implementable por separado. Orden sugerido: 1→6.

## 1. Sistema de tokens de color y tipografía
**Qué:** reemplazar las variables `:root` actuales por una paleta cohesiva y una tipografía display.
```css
:root{
  --bg:#07080c;            /* más profundo que el actual #0d0f14 */
  --surface:#101420;       /* tarjetas */
  --surface-2:#161b2c;     /* inputs, modales */
  --border:#232a40;
  --txt:#f2f4fa; --muted:#9aa3b8;
  --accent:#ffb340;        /* ámbar KorLab */
  --accent-soft:rgba(255,179,64,.14);
  --danger:#ff5d5d; --ok:#4ade80;
  --radius:16px; --radius-sm:10px;
  --shadow:0 8px 32px rgba(0,0,0,.45);
}
```
- Fuente: `Inter` o `Outfit` desde Google Fonts (`<link>` en `<head>`), pesos 400/600/700. Títulos en 700 con `letter-spacing:-0.02em`.
- Quitar `text-transform:uppercase` del título "Escenas guardadas"; usar tamaño 17px weight 700 color `--txt` (el muted-uppercase se ve datado).

## 2. Tarjetas de escena con capa de profundidad
**Qué:** las tarjetas (` .card`) deben sentirse táctiles, no planas.
- Miniatura a **altura mayor (150px)** con `border-radius` superior y un **degradado inferior oscuro** superpuesto (`.card::after` con `linear-gradient(180deg, transparent 55%, rgba(0,0,0,.55))`) para que el nombre se lea sobre el color.
- Nombre **dentro** de la miniatura (posición absoluta abajo-izquierda), no debajo. Meta (usuario) como chip pequeño arriba-derecha con fondo `rgba(0,0,0,.35)` y `backdrop-filter:blur(8px)`.
- Hover/active: `transform:scale(1.02)` + `box-shadow:0 12px 40px color-mix(in srgb, <color dominante> 30%, transparent)`.
- Añadir botón fantasma "▶ Aplicar" que aparece en hover (desktop) y siempre visible 80% en móvil.

## 3. Segmented control en vez de botones "Cuarto / Cilindro HSV"
**Qué:** reemplazar `.modeswitch` (2 botones sueltos) por un segmented control tipo iOS:
```css
.segmented{display:flex; background:var(--surface-2); border:1px solid var(--border); border-radius:999px; padding:3px}
.segmented button{border:none; background:transparent; color:var(--muted); padding:7px 16px; border-radius:999px; font-size:13px; cursor:pointer; transition:all .2s}
.segmented button.active{background:var(--accent); color:#0b0c10; font-weight:600}
```
Animar el cambio de modo con `transition:opacity .2s` en el canvas (fade out/in al re-render).

## 4. Header de app + título de sección
**Qué:** hoy la página abre directamente con el selector de usuario. Añadir barra superior:
- Título "KorLab Lights" (18px, 700) a la izquierda; a la derecha un **indicador de conexión** (punto verde/gris + "Hub conectado / Sin hub") — dejar el estado como variable JS `hubEstado` lista para integrarse al WS real.
- Selector de usuario: convertirlo en un **chip de avatar** (círculo con la inicial del usuario + nombre + chevron) que abre un popover de lista en vez del `<select>` nativo; en móvil se ve mucho mejor. Mantener el `select` oculto como fuente de verdad para no romper la lógica existente (`usuarioActual()`).

## 5. Editor: secciones agrupadas con encabezados
**Qué:** el modal del editor es una lista plana de 8 controles. Agrupar:
- **"Color"**: barra de matiz + 4 sliders. Sliders nuevos con estilo custom (pista fina 4px, thumb 22px blanco con sombra; pista de saturación con degradado gris→color vivo y pista de brillo degradado negro→blanco, para que el slider mismo muestre lo que controla):
```css
input[type=range]{appearance:none; height:4px; border-radius:2px; background:var(--border)}
input[type=range]::-webkit-slider-thumb{appearance:none; width:22px; height:22px; border-radius:50%; background:#fff; box-shadow:0 2px 8px rgba(0,0,0,.5); cursor:grab}
```
- **"Movimiento"**: velocidad + escala, en una fila de 2 chips con stepper (−/+) en vez de `input[type=number]`.
- Los valores numéricos como **badge pill** a la derecha del label (`background:var(--accent-soft); color:var(--accent); padding:2px 8px; border-radius:999px`).
- Previews: elevarlos con `box-shadow:var(--shadow)` y label en `font-size:12px` centrado.

## 6. Microinteracciones (lista completa para el agente)
- Al guardar escena: cerrar modal con animación (`.overlay{transition:opacity .25s}` + scale del modal de 0.96→1 al abrir) y **toast** "Escena guardada" (div fijo abajo, 2.5s, `--surface-2` + borde `--ok`).
- Al tocar "Aplicar escena": estado de carga en el botón (spinner CSS, 600ms) antes del alert; cuando exista integración real, es el lugar del feedback de error (`--danger`).
- `prefers-reduced-motion: reduce` → desactivar todas las transiciones.
- Botón primario: `background:linear-gradient(180deg,#ffc056,#f2a430)` + `box-shadow:0 6px 20px rgba(242,164,48,.35)`; `:active{transform:scale(.98)}`.
- Empty state ("Sin escenas para este usuario"): icono de bombilla en SVG inline 40px color `--border` + texto centrado, en vez del recuadro punteado.

## Notas de integración (no romper)
- Mantener TODOS los ids/funciones existentes: `userSelect`, `hueBar`, `satMin/satMax/valMin/valMax`, `speed`, `scale`, `pvGlow`, `pvHsv`, `dtGlow`, `dtHsv`, `detailJson`, `renderEscenas()`, `paramsDeFormulario()`, `pintarGlow()`, `pintarCilindro()`, `pintarHueBar()`, `syncRange()`.
- Los canvas internos (320×240) no cambiar tamaño de bitmap; solo CSS puede escalarlos.
- localStorage `korlab_lights_v1`: mismo schema `{usuarios, escenas}`.
- Verificación obligatoria tras cada cambio: abrir en navegador, probar (a) crear usuario nuevo, (b) crear escena con rango que cruza 0°, (c) mover los 4 sliders y confirmar que ambos previews cambian, (d) aplicar escena desde tarjeta. Screenshot de cada estado.
