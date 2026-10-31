"""arcpy adapter (v1 skeleton): the only file that touches arcpy.

Responsibilities, mirroring the pattern in arcgis-qa-toolbox:
- read a feature class into (records, coords, schema) for the pure core
- write forged output into a fresh file GDB, carrying domains/subtypes
- export .lyrx files from a source project; rewrite via demoforge.lyrx
- NEVER write into the source workspace: demoforge outputs are always a
  new, separate GDB. The source is read-only on principle.

Run inside an ArcGIS Pro Python environment. Everything here is thin;
if a function grows logic worth testing, the logic moves to src/.
"""

from __future__ import annotations

from demoforge.relocate import AffineTransform


def read_feature_class(fc: str, fields: list[str] | None = None):
    """Yield (attributes: dict, geojson_coords, geom_type) per feature."""
    import arcpy

    desc = arcpy.Describe(fc)
    field_names = fields or [
        f.name for f in arcpy.ListFields(fc)
        if f.type not in ("Geometry",) and f.name != desc.OIDFieldName
    ]
    with arcpy.da.SearchCursor(fc, [*field_names, "SHAPE@"]) as cursor:
        for row in cursor:
            attrs = dict(zip(field_names, row[:-1]))
            geom = row[-1]
            gj = geom.__geo_interface__ if geom else None
            yield attrs, (gj["coordinates"] if gj else None), (gj["type"] if gj else None)


def write_feature_class(
    out_gdb: str,
    name: str,
    template_fc: str,
    features,  # iterable of (attrs: dict, coords, geom_type)
    transform: AffineTransform,
    spatial_reference,
):
    """Create a FC from the template's schema and insert transformed rows."""
    import arcpy

    arcpy.management.CreateFeatureclass(
        out_gdb, name,
        geometry_type=arcpy.Describe(template_fc).shapeType.upper(),
        template=template_fc,
        spatial_reference=spatial_reference,
    )
    out = f"{out_gdb}/{name}"
    first = True
    cursor = None
    try:
        for attrs, coords, geom_type in features:
            if first:
                cursor = arcpy.da.InsertCursor(out, [*attrs.keys(), "SHAPE@"])
                first = False
            new_coords = transform.apply_coords(coords) if coords else None
            geom = (
                arcpy.AsShape({"type": geom_type, "coordinates": new_coords}, True)
                if new_coords else None
            )
            cursor.insertRow([*attrs.values(), geom])
    finally:
        if cursor is not None:
            del cursor
    return out


# TODO v1:
# - export_lyrx(project, layer) -> path (arcpy.mp SaveACopy)
# - carry attribute domains: arcpy.da.ListDomains + CreateDomain/AddCodedValue
# - metadata scrub: arcpy.metadata.Metadata — feed title/summary/credits
#   through demoforge.audit before writing
# - drop attachments by default; opt-in passthrough with audit warning
