# -*- coding: utf-8 -*-
"""Demoforge Extract — ArcGIS Pro Python Toolbox (the on-ramp).

Selects layers from the map (local feature classes OR hosted feature
layers — anything a SearchCursor can read), or sweeps an entire
geodatabase, and stages everything for demoforge: one GeoJSON per layer
plus a drafted demoforge_job.json with suggested field policies.

Install demoforge into the Pro conda environment (pip install -e .) and
add this .pyt in Catalog. The tool only READS sources; staging output is
always a separate folder.
"""

import json
import os

import arcpy

from demoforge.staging import build_job_config


class Toolbox:
    def __init__(self):
        self.label = "Demoforge"
        self.alias = "demoforge"
        self.tools = [ExtractToDemoforge]


class ExtractToDemoforge:
    def __init__(self):
        self.label = "Extract To Demoforge"
        self.description = (
            "Exports selected layers (local or hosted) or every feature "
            "class in a geodatabase to a demoforge staging folder: GeoJSON "
            "per layer + a drafted job config with suggested field policies."
        )
        self.canRunInBackground = True

    def getParameterInfo(self):
        layers = arcpy.Parameter(
            displayName="Input Layers (local or hosted)",
            name="in_layers",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input",
            multiValue=True,
        )
        gdb = arcpy.Parameter(
            displayName="Or: entire Geodatabase",
            name="in_gdb",
            datatype="DEWorkspace",
            parameterType="Optional",
            direction="Input",
        )
        out_folder = arcpy.Parameter(
            displayName="Staging Folder (created if missing)",
            name="out_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        return [layers, gdb, out_folder]

    def execute(self, parameters, messages):
        layer_param, gdb_param, folder_param = parameters
        staging = folder_param.valueAsText
        os.makedirs(staging, exist_ok=True)

        sources = []
        if layer_param.values:
            sources += [(l, None) for l in layer_param.values]
        source_workspace = ""
        if gdb_param.valueAsText:
            source_workspace = gdb_param.valueAsText
            walk = arcpy.da.Walk(source_workspace, datatype="FeatureClass")
            for dirpath, _dirnames, filenames in walk:
                sources += [(os.path.join(dirpath, fc), fc) for fc in filenames]
        if not sources:
            raise arcpy.ExecuteError("select layers, a geodatabase, or both")

        layer_fields = {}
        for src, forced_name in sources:
            name = forced_name or arcpy.Describe(src).baseName
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            out_path = os.path.join(staging, f"{safe}.geojson")
            arcpy.AddMessage(f"extracting {name} -> {out_path}")

            desc = arcpy.Describe(src)
            fields = [
                f.name for f in arcpy.ListFields(src)
                if f.type != "Geometry" and f.name != desc.OIDFieldName
            ]
            features = []
            with arcpy.da.SearchCursor(src, [*fields, "SHAPE@"]) as cursor:
                for row in cursor:
                    geom = row[-1]
                    gj = geom.__geo_interface__ if geom else None
                    features.append({
                        "type": "Feature",
                        "geometry": gj,
                        "properties": dict(zip(fields, row[:-1])),
                    })
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump({"type": "FeatureCollection", "features": features},
                          fh, default=str)
            layer_fields[safe] = fields
            arcpy.AddMessage(f"  {len(features)} features, {len(fields)} fields")

        job = build_job_config(layer_fields, source_workspace=source_workspace)
        job_path = os.path.join(staging, "demoforge_job.json")
        with open(job_path, "w", encoding="utf-8") as fh:
            json.dump(job, fh, indent=2)

        arcpy.AddMessage(f"job config drafted: {job_path}")
        arcpy.AddWarning(
            "Review every suggested policy and fill in the blocklist and "
            "seed before forging — suggestions are drafts, not decisions."
        )
