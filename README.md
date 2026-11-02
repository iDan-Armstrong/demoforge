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
             survives exactly. Per-vertex jitter breaks topology; demoforge won't.
             A pure move keeps the *shape* exact, so a distinctive outline is still
             recognizable — so `scramble` (0–100%, seed-driven) adds anisotropic
             scale + shear to distort proportions until the shape no longer matches,
             staying a single affine map so topology is still exact. Honest limit:
             it's a global linear map, so it defeats casual identification, not a
             determined analyst; non-linear morphing is the v2 direction.

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

## Workflow

1. **Extract (ArcGIS Pro):** in the Catalog pane, right-click **Toolboxes →
   Add Toolbox** and pick `toolbox/DemoForgeExtract.pyt` from your clone — no
   install needed. The toolbox adds its own `src/` folder to the path when it
   loads, so it runs in the stock `arcgispro-py3` environment (if you'd rather
   `pip install -e .` into a cloned environment, it uses that instead). Run
   *Extract To Demoforge* — select map layers (local feature classes or hosted
   feature layers), sweep a whole geodatabase, and/or paste hosted layer URLs
   authenticated by a saved vault connection (no reliance on the Pro session's
   sign-in). It stages one GeoJSON per
   layer plus a drafted `demoforge_job.json` with **suggested** field policies
   (owner-ish fields → fake person, id-ish → format-preserving fake, system
   fields → drop). Suggestions are drafts; you review every one.
2. **Develop & test (local workbench):** `python devtool/server.py` →
   http://localhost:8765 — a zero-dependency local web UI. Load a staged GeoJSON,
   tune seed/target/rotation/policies/blocklist, forge, and see before/after
   previews, join-safe faked attributes, and the leak-audit report live.
   The **Connections** menu manages ArcGIS Online / Portal credentials
   (sign-in, OAuth app, API key) in a local vault: metadata in
   `~/.demoforge/vault.json`, secrets DPAPI-encrypted per-user on Windows
   (OS keyring elsewhere via `pip install keyring`), never shown again after
   save, testable against the portal with one click.
3. **Forge for real:** the same config drives the pipeline over the full dataset;
   output ships only after the audit report is signed off item by item.

## Credential storage

The vault is local-only by design: no cloud component, no sync, no telemetry.
The only network traffic a credential ever causes is the HTTPS token request to
the portal you configured. `~/.demoforge/vault.json` holds metadata only — the
secret itself is DPAPI-encrypted to your Windows account (useless to other
users or copied off-machine), or lives in the OS keyring elsewhere. The
workbench never displays a secret after save, never logs one, and its localhost
API rejects cross-site requests.

The honest limit, shared with Windows Credential Manager and every browser
password store: a process running *as you* can decrypt what was encrypted *to
you*. If your threat model needs more than that, a passphrase-derived key is
the upgrade path — at the cost of a prompt every session.

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
