# Schematic Pipeline Migration Notes

## Behavior changes

- `auto_layout_schematic` now defaults to connectivity-safe mode.
- If existing net connectivity is detected and `preserveConnectivity=false`, layout is refused unless `allowUnsafeLayout=true` is passed.
- In safe mode, layout rebuilds managed pin-to-net connections and verifies net membership consistency before returning success.
- `generate_netlist` now supports `includeTemplates` (default `false`) so `_TEMPLATE_*` symbols stay out of normal output.
- `add_schematic_component` and dynamic template loading are now idempotent for existing references.
- `export_schematic_pdf` now uses a shared CLI resolver that checks `KICAD_CLI`/`KICAD_CLI_PATH`, `PATH`, and platform-specific fallback paths.

## Compatibility

- Existing tool names are unchanged.
- Existing `auto_layout_schematic` calls continue to work; the new safety behavior applies automatically.
- To intentionally run unsafe layout behavior, set `allowUnsafeLayout=true`.

## Coordinate system note

- KiCad symbol-library pin coordinates use normal math orientation (`+Y` up).
- Placed schematic coordinates use inverted screen orientation (`+Y` down).
- When mapping pin coordinates from symbol space to schematic space, `pin_y` must be negated before rotation and translation.
- Electrical connectivity is coordinate-exact at grid points, so off-grid values can silently break net detection and reconnection.
