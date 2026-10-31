# demoforge — turn proprietary GIS projects into shareable demos

![CI](https://github.com/iDan-Armstrong/demoforge/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-v1%20in%20progress-orange)

Every consulting GIS career has the same problem: decades of good work, none of it
shareable. demoforge takes an existing geodatabase project and forges a demo-safe
version — **relocated** to a fictional place, **anonymized** in its attributes,
**audited** for leaks, with the **symbology and labeling carried over** — without
recreating layers and datasets by hand.

```
relocate  →  one affine transform (translate/rotate/scale) moves the whole project
             to a fictional AOI. Affine on purpose: every spatial relationship —
             shared parcel edges, pipe-to-manhole connectivity, containment —
             survives exactly. Jitter breaks topology; v1 refuses to.

fake      →  deterministic attribute anonymization: HMAC(seed, value) drives the
             fakes, so the same real ID maps to the same fake ID everywhere and
             every join in the project survives. Format-preserving IDs
             ('MH-1042a' → 'QX-7391c'), generated names/addresses/places.

audit     →  the trust feature. Finds what scrubbing did NOT handle: your
             blocklist terms (client names, towns), email/phone/SSN-shaped
             strings, suspiciously-named fields with no policy. Produces a
             markdown report a human signs off on, item by item. It reports;
             it never silently 'fixes'.

carry     →  .lyrx layer files are CIM JSON keyed to field names; demoforge keeps
             the schema, so cartography ports by rewriting dataset paths. Pure
             JSON — tested in CI without an ArcGIS license.
```

## The honest caveat

**Anonymized is not the same as non-proprietary.** demoforge removes
*identifiability*; your contract decides *ownership*. Schema design, data models,
and symbology standards can themselves be client work product. The audit report
makes your sign-off informed — it does not make it unnecessary.

## Status

v1 core (this repo, pure Python, CI-tested): relocation planner, deterministic
faker, leak audit, .lyrx rewrite. The arcpy adapter (`adapters/arcpy_io.py`) is a
working skeleton: FC read/write with transform is in; domains carryover, metadata
scrub, and .aprx layer export are the open TODOs. v2 (not promised): topology-aware
geometry morphing with shared-vertex pooling.

## Develop

```bash
pip install -e ".[dev]"
pytest          # pure-core tests; no ArcGIS required
ruff check .
```

## Architecture

Same boundary discipline as my other repos
([arcgis-qa-toolbox](https://github.com/iDan-Armstrong/arcgis-qa-toolbox),
[geo-etl-pipeline](https://github.com/iDan-Armstrong/geo-etl-pipeline)): everything
decision-shaped lives in `src/demoforge/` as pure Python with tests; arcpy appears
only in `adapters/`, and only as plumbing.

## License

MIT
