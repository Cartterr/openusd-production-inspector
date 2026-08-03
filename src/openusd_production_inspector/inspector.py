"""Read-only inspection and validation for a local OpenUSD stage."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from pxr import Sdf, Tf, Usd


class StageLoadError(RuntimeError):
    """Raised when OpenUSD cannot open a supplied stage."""


def _open_stage(path: Path, load: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll) -> Usd.Stage:
    try:
        stage = Usd.Stage.Open(str(path), load=load)
    except Tf.ErrorException as error:
        raise StageLoadError(f"Unable to open USD stage: {path}") from error
    if stage is None:
        raise StageLoadError(f"Unable to open USD stage: {path}")
    return stage


def _finding(code: str, severity: str, message: str, subject: str | None = None) -> dict[str, str]:
    finding = {"code": code, "severity": severity, "message": message}
    if subject:
        finding["subject"] = subject
    return finding


def _asset_findings(stage_path: Path, layers: list[Any]) -> tuple[list[str], list[dict[str, str]]]:
    references: set[str] = set()
    findings: list[dict[str, str]] = []
    for layer in layers:
        for reference in layer.GetExternalReferences():
            reference_text = str(reference)
            references.add(reference_text)
            candidate = Path(reference_text)
            if not candidate.is_absolute():
                candidate = stage_path.parent / candidate
            if not candidate.exists():
                findings.append(_finding("unresolved-asset", "error", "Referenced asset does not exist.", reference_text))
    return sorted(references), findings


def inspect_stage(path: str | Path, name_pattern: str | None = None) -> dict[str, Any]:
    """Inspect a stage without changing it and return a deterministic report."""
    stage_path = Path(path).resolve()
    stage = _open_stage(stage_path)

    layers = list(stage.GetLayerStack())
    prims = list(stage.Traverse())
    default_prim = stage.GetDefaultPrim()
    findings: list[dict[str, str]] = []
    if not default_prim:
        findings.append(_finding("missing-default-prim", "error", "Stage has no valid default prim."))
    root_layer = stage.GetRootLayer()
    up_axis = stage.GetMetadata("upAxis")
    meters_per_unit = stage.GetMetadata("metersPerUnit")
    has_authored_up_axis = root_layer.pseudoRoot.HasInfo("upAxis")
    has_authored_meters_per_unit = root_layer.pseudoRoot.HasInfo("metersPerUnit")
    if not has_authored_up_axis:
        findings.append(_finding("missing-up-axis", "warning", "Stage has no authored upAxis metadata."))
    if not has_authored_meters_per_unit:
        findings.append(_finding("missing-meters-per-unit", "warning", "Stage has no authored metersPerUnit metadata."))

    if name_pattern:
        expression = re.compile(name_pattern)
        for prim in prims:
            if not expression.fullmatch(prim.GetName()):
                findings.append(_finding("name-pattern-violation", "warning", "Prim name does not match the configured pattern.", str(prim.GetPath())))

    references, asset_findings = _asset_findings(stage_path, layers)
    findings.extend(asset_findings)
    schema_counts = Counter(prim.GetTypeName() or "untyped" for prim in prims)
    findings.sort(key=lambda item: (item["severity"], item["code"], item.get("subject", "")))

    return {
        "stage": str(stage_path),
        "default_prim": str(default_prim.GetPath()) if default_prim else None,
        "up_axis": str(up_axis) if up_axis else None,
        "meters_per_unit": meters_per_unit,
        "authored_metadata": {
            "up_axis": has_authored_up_axis,
            "meters_per_unit": has_authored_meters_per_unit,
        },
        "layer_stack": [layer.identifier for layer in layers],
        "prim_count": len(prims),
        "schema_counts": dict(sorted(schema_counts.items())),
        "external_references": references,
        "findings": findings,
    }


def stage_summary(path: str | Path) -> dict[str, Any]:
    """Return the production-facing stage summary contract."""
    stage_path = Path(path).resolve()
    stage = _open_stage(stage_path)
    report = inspect_stage(stage_path)
    loadable = set(stage.FindLoadable())
    loaded = set(stage.GetLoadSet())
    return {
        "stage": report["stage"],
        "default_prim": report["default_prim"],
        "up_axis": report["up_axis"],
        "meters_per_unit": report["meters_per_unit"],
        "start_time": stage.GetStartTimeCode(),
        "end_time": stage.GetEndTimeCode(),
        "prim_count": report["prim_count"],
        "schemas": sorted(report["schema_counts"]),
        "root_layer": (stage.GetRootLayer().realPath or stage.GetRootLayer().identifier).replace("\\", "/"),
        "loaded": loadable.issubset(loaded),
        "unloaded_prim_count": len(loadable - loaded),
    }


def _list_editor_items(editor: Any) -> list[Any]:
    items: list[Any] = []
    for attribute in ("explicitItems", "prependedItems", "appendedItems", "addedItems"):
        items.extend(getattr(editor, attribute, []))
    return items


def inspect_dependencies(path: str | Path) -> dict[str, Any]:
    """Classify external composition dependencies authored by the root layer."""
    stage_path = Path(path).resolve()
    stage = _open_stage(stage_path, Usd.Stage.LoadNone)
    layer = stage.GetRootLayer()
    dependencies: list[dict[str, Any]] = []

    def add(kind: str, authored_path: str, source_layer: Sdf.Layer = layer) -> None:
        absolute = Sdf.ComputeAssetPathRelativeToLayer(source_layer, authored_path)
        resolved = str(Path(absolute).resolve()).replace("\\", "/")
        dependencies.append(
            {
                "kind": kind,
                "authored_path": authored_path,
                "resolved_path": resolved,
                "exists": Path(absolute).exists(),
            }
        )

    for sublayer in layer.subLayerPaths:
        add("sublayer", sublayer)

    def visit(spec_path: Sdf.Path) -> None:
        spec = layer.GetObjectAtPath(spec_path)
        if not isinstance(spec, Sdf.PrimSpec):
            return
        for reference in _list_editor_items(spec.referenceList):
            if reference.assetPath:
                add("reference", reference.assetPath)
        for payload in _list_editor_items(spec.payloadList):
            if payload.assetPath:
                add("payload", payload.assetPath)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)

    texture_extensions = {".exr", ".hdr", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".tx"}
    for used_layer in stage.GetUsedLayers():
        def visit_asset_attributes(spec_path: Sdf.Path) -> None:
            spec = used_layer.GetObjectAtPath(spec_path)
            if not isinstance(spec, Sdf.AttributeSpec):
                return
            value = spec.default
            asset_paths = [value] if isinstance(value, Sdf.AssetPath) else []
            if isinstance(value, (list, tuple)):
                asset_paths.extend(item for item in value if isinstance(item, Sdf.AssetPath))
            for asset_path in asset_paths:
                authored_path = asset_path.path
                if Path(authored_path).suffix.lower() in texture_extensions:
                    add("texture", authored_path, used_layer)

        used_layer.Traverse(Sdf.Path.absoluteRootPath, visit_asset_attributes)
    unique = {
        (item["kind"], item["authored_path"]): item
        for item in dependencies
    }
    ordered = sorted(unique.values(), key=lambda item: (item["kind"], item["authored_path"]))
    return {
        "stage": str(stage_path),
        "sublayers": [item for item in ordered if item["kind"] == "sublayer"],
        "references": [item for item in ordered if item["kind"] == "reference"],
        "payloads": [item for item in ordered if item["kind"] == "payload"],
        "textures": [item for item in ordered if item["kind"] == "texture"],
        "resolved": [item for item in ordered if item["exists"]],
        "missing": [item for item in ordered if not item["exists"]],
        "unresolved": [item for item in ordered if not item["exists"]],
    }


def inspect_composition(path: str | Path, prim_path: str) -> dict[str, Any]:
    """Explain the composed opinions and selections for one prim."""
    stage_path = Path(path).resolve()
    stage = _open_stage(stage_path)
    prim = stage.GetPrimAtPath(prim_path)
    if not prim:
        raise StageLoadError(f"Prim does not exist: {prim_path}")
    variants = prim.GetVariantSets()
    prim_stack = [
        {
            "layer": (spec.layer.realPath or spec.layer.identifier).replace("\\", "/"),
            "path": str(spec.path),
            "specifier": str(spec.specifier),
            "type_name": spec.typeName,
        }
        for spec in prim.GetPrimStack()
    ]
    dependencies = inspect_dependencies(stage_path)
    return {
        "stage": str(stage_path),
        "prim": str(prim.GetPath()),
        "layer_stack": [
            (layer.realPath or layer.identifier).replace("\\", "/")
            for layer in stage.GetLayerStack(includeSessionLayers=True)
        ],
        "prim_stack": prim_stack,
        "references": dependencies["references"],
        "payloads": dependencies["payloads"],
        "variant_selections": {
            name: variants.GetVariantSet(name).GetVariantSelection()
            for name in sorted(variants.GetNames())
        },
        "authored_opinions": prim_stack,
    }


def validate_stage(path: str | Path) -> dict[str, Any]:
    """Apply the six version-0.1 production asset rules."""
    stage_path = Path(path).resolve()
    stage = _open_stage(stage_path, Usd.Stage.LoadNone)
    root_layer = stage.GetRootLayer()
    default_prim = stage.GetDefaultPrim()
    dependencies = inspect_dependencies(stage_path)
    asset = stage.GetPrimAtPath("/Asset")
    lod_exists = bool(asset) and "lod" in asset.GetVariantSets().GetNames()

    rules = [
        ("default-prim-exists", bool(default_prim), f"Default prim exists: {default_prim.GetPath() if default_prim else 'none'}"),
        ("default-prim-is-asset", bool(default_prim) and str(default_prim.GetPath()) == "/Asset", f"Default prim is /Asset: {default_prim.GetPath() if default_prim else 'none'}"),
        ("up-axis-authored", root_layer.pseudoRoot.HasInfo("upAxis"), f"Up axis explicitly authored: {stage.GetMetadata('upAxis')}"),
        ("meters-per-unit-authored", root_layer.pseudoRoot.HasInfo("metersPerUnit"), f"Meters per unit explicitly authored: {stage.GetMetadata('metersPerUnit')}"),
        ("dependencies-resolve", not dependencies["missing"], f"External dependencies resolve: {len(dependencies['missing'])} missing"),
        ("lod-variant-exists", lod_exists, "Required variant set exists: lod"),
    ]
    checks = [
        {"rule": rule, "status": "PASS" if passed else "FAIL", "message": message}
        for rule, passed, message in rules
    ]
    error_count = sum(check["status"] == "FAIL" for check in checks)
    return {
        "stage": str(stage_path),
        "valid": error_count == 0,
        "error_count": error_count,
        "warning_count": 0,
        "checks": checks,
    }
