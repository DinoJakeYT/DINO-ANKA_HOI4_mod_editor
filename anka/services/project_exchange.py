"""Portable ANKA projects and Dino's HOI4 Mod Builder (.hmb) export."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..domain.mod import Mod, ModContext
from .country_service import CountryService
from .focus_service import FocusService

EDITABLE_EXTENSIONS = {
    ".txt", ".yml", ".yaml", ".gfx", ".gui", ".asset",
    ".mod", ".json", ".csv", ".lua",
}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _atomic_json(path: Path, payload: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary.replace(path)


def capture_source_files(root: Path) -> tuple[dict[str, str], int]:
    """Mirror HMB's portable-text limits and safe relative-path rules."""
    files: dict[str, str] = {}
    skipped = 0
    total = 0
    if not root.is_dir():
        return files, skipped
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EDITABLE_EXTENSIONS \
                or path.name.lower().endswith(".bak"):
            continue
        rel = path.relative_to(root).as_posix()
        if rel != "descriptor.mod" and "/" not in rel and path.suffix.lower() == ".mod":
            skipped += 1
            continue
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
                skipped += 1
                continue
            files[rel] = path.read_text(encoding="utf-8-sig", errors="replace")
            total += size
        except OSError:
            skipped += 1
    return files, skipped


def save_anka(context: ModContext, path: Path) -> dict:
    files, skipped = capture_source_files(context.mod.path)
    payload = {
        "Format": "ANKA_PROJECT",
        "FormatVersion": 1,
        "SavedAtUtc": datetime.now(timezone.utc).isoformat(),
        "Name": context.mod.name,
        "ModId": context.mod.id,
        "ModPath": str(context.mod.path),
        "DescriptorPath": (str(context.mod.descriptor_path)
                           if context.mod.descriptor_path else ""),
        "GamePath": str(context.game_path),
        "Dependencies": list(context.mod.dependencies),
        "ReplacePaths": list(context.mod.replace_paths),
        "SourceFiles": files,
        "SkippedFiles": skipped,
    }
    _atomic_json(path, payload)
    return payload


def load_anka(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("Format") != "ANKA_PROJECT" or payload.get("FormatVersion") != 1:
        raise ValueError("Unsupported or invalid ANKA project file")
    return payload


def mod_from_anka(payload: dict) -> Mod:
    mod_path = Path(payload.get("ModPath", ""))
    if not mod_path.is_dir():
        raise FileNotFoundError(
            f"The saved mod folder does not exist on this computer: {mod_path}")
    descriptor = payload.get("DescriptorPath", "")
    return Mod(
        id=payload.get("ModId") or mod_path.name,
        name=payload.get("Name") or mod_path.name,
        path=mod_path,
        descriptor_path=Path(descriptor) if descriptor else None,
        dependencies=list(payload.get("Dependencies") or []),
        replace_paths=list(payload.get("ReplacePaths") or []),
    )


def restore_anka(payload: dict, destination: Path) -> Mod:
    """Restore a portable text snapshot when its original folder is unavailable."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in (payload.get("SourceFiles") or {}).items():
        relative_path = Path(relative)
        target = (destination / relative_path).resolve()
        if relative_path.is_absolute() or destination not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
    descriptor = destination / "descriptor.mod"
    return Mod(
        id=payload.get("ModId") or destination.name,
        name=payload.get("Name") or destination.name,
        path=destination,
        descriptor_path=descriptor if descriptor.exists() else None,
        dependencies=list(payload.get("Dependencies") or []),
        replace_paths=list(payload.get("ReplacePaths") or []),
    )


def _safe_hmb_id(value: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return value or "anka_project"


def _country_to_hmb(service: CountryService, ref) -> dict:
    history = service.get_history(ref.tag)
    politics = service.get_politics(ref.tag)
    popularity = service.get_popularities(ref.tag)
    color = service.get_color(ref).rgb or (90, 120, 160)
    names = service.get_names(ref.tag)
    name = names.get("english") or ref.name or ref.tag
    ruling = politics.get("ruling_party") or "neutrality"
    known = {"democratic", "fascism", "communism", "neutrality"}
    return {
        "Tag": ref.tag, "Name": name, "DefiniteName": name, "Adjective": name,
        "Red": color[0], "Green": color[1], "Blue": color[2],
        "CapitalState": int(history.get("capital") or 1),
        "Ideology": ruling,
        "GraphicalCulture": service.graphical_culture(ref)
        or "western_european_gfx",
        "GraphicalCulture2d": (
            service.graphical_culture(ref) or "western_european_gfx"
        ).replace("_gfx", "_2d"),
        "DefinitionFileName": Path(ref.rel_file).name,
        "HistoryFileName": "",
        "IdeologyNames": {}, "PartyNames": {}, "PartyLongNames": {},
        "DemocraticPopularity": popularity.get("democratic", 0),
        "FascismPopularity": popularity.get("fascism", 0),
        "CommunismPopularity": popularity.get("communism", 0),
        "NeutralityPopularity": popularity.get("neutrality", 0),
        "CustomIdeologyPopularities": {
            key: value for key, value in popularity.items() if key not in known},
        "ElectionsAllowed": politics.get("elections_allowed", "no") == "yes",
        "ElectionFrequency": int(politics.get("election_frequency") or 48),
        "LastElection": politics.get("last_election") or "1936.1.1",
        "Stability": round(float(history.get("set_stability") or 0.5) * 100),
        "WarSupport": round(float(history.get("set_war_support") or 0.5) * 100),
        "ResearchSlots": int(history.get("set_research_slots") or 3),
        "Convoys": 0, "StartingHistoryEffects": "", "DatedHistory": [],
    }


def _focus_to_hmb(service: FocusService, focus) -> dict:
    groups = focus.prerequisites
    prereqs = list(dict.fromkeys(fid for group in groups for fid in group))
    mode = "OR" if len(groups) == 1 and len(groups[0]) > 1 else "AND"
    key = focus.text or focus.id
    return {
        "Id": focus.id,
        "Name": service.focus_name(key, "english"),
        "Description": service.focus_desc(key, "english"),
        "Icon": focus.icon or "GFX_goal_unknown", "IconSource": "",
        "X": float(focus.x * 180), "Y": float(focus.y * 130),
        "Cost": round(focus.cost), "SearchFilters": focus.search_filters,
        "WillLeadToWar": bool(focus.will_lead_to_war_with),
        "Prerequisites": prereqs, "PrerequisiteMode": mode,
        "MutuallyExclusive": focus.mutually_exclusive,
        "RelativePositionId": focus.relative_position_id or "",
        "CancelIfInvalid": focus.get_flag("cancel_if_invalid"),
        "ContinueIfInvalid": focus.get_flag("continue_if_invalid"),
        "AvailableIfCapitulated": focus.get_flag("available_if_capitulated"),
        "BypassIfUnavailable": focus.get_flag("bypass_if_unavailable"),
        "AllowBranch": focus.get_script("allow_branch"),
        "Bypass": focus.get_script("bypass"),
        "SelectEffect": focus.get_script("select_effect"),
        "CompleteTooltip": focus.get_script("complete_tooltip"),
        "Available": focus.get_script("available"),
        "CompletionReward": focus.get_script("completion_reward"),
        "AiWillDo": focus.get_script("ai_will_do"),
    }


def export_hmb(context: ModContext, path: Path) -> dict:
    source_files, skipped = capture_source_files(context.mod.path)
    country_service = CountryService(context)
    countries = [
        _country_to_hmb(country_service, ref)
        for ref in country_service.list_tags(include_vanilla=False)
        if not ref.cosmetic
    ]
    focus_service = FocusService(context)
    trees: list[dict] = []
    for ref in focus_service.list_trees(include_vanilla=False):
        doc = focus_service.load(ref)
        tree = doc.tree
        focuses = doc.focuses if tree is not None else doc.all_focuses()
        position = tree.continuous_focus_position if tree else None
        initial = tree.initial_show_position if tree else None
        trees.append({
            "Id": tree.id if tree else ref.id,
            "Name": (tree.id if tree else ref.id).replace("_", " ").title(),
            "Kind": ("country" if tree else
                     "joint" if ref.kind == "joint" else "shared"),
            "Default": tree.default if tree else False,
            "ResetOnCivilWar": tree.reset_on_civilwar if tree else False,
            "ContinuousFocusPosition": position is not None,
            "ContinuousFocusX": position[0] if position else 50,
            "ContinuousFocusY": position[1] if position else 1000,
            "InitialShowPosition": initial is not None,
            "InitialShowX": initial[0] if initial else 0,
            "InitialShowY": initial[1] if initial else 0,
            "CountryTags": [ref.country] if ref.country else [],
            "CountryTrigger": tree.get_country_script() if tree else "",
            "SharedFocusIds": tree.shared_focus_refs if tree else [],
            "Focuses": [_focus_to_hmb(focus_service, f) for f in focuses],
        })
    payload = {
        "FormatVersion": 4,
        "Name": context.mod.name,
        "Id": _safe_hmb_id(context.mod.id),
        "SupportedVersion": context.mod.supported_version or "1.19.*",
        "Hoi4InstallPath": str(context.game_path),
        "SourceModPath": str(context.mod.path),
        "SourceFiles": source_files,
        "PortableSourceImported": bool(source_files),
        "RawFileOverrides": {},
        "OverhaulMode": False, "ReplaceVanillaIdeologies": False,
        "ScrollableIdeologyList": False,
        "IsSubmod": bool(context.mod.dependencies),
        "ParentModName": (context.mod.dependencies[0]
                          if context.mod.dependencies else ""),
        "OutputPath": str(context.mod.path.parent),
        "FocusTreeId": trees[0]["Id"] if trees else "my_focus_tree",
        "CountryTag": (trees[0]["CountryTags"][0]
                       if trees and trees[0]["CountryTags"] else "TAG"),
        "Tags": context.mod.tags or ["Alternative History"],
        "Focuses": [], "FocusTrees": trees, "Countries": countries,
        "Ideas": [], "Events": [], "SuperEvents": [],
        "DecisionCategories": [], "Characters": [], "Ideologies": [],
        "ScriptedTriggers": [], "ScriptedEffects": [], "OnActions": [],
        "DynamicModifiers": [], "CountryLeaderTraits": [],
        "UnitLeaderTraits": [], "OrdersOfBattle": [], "Bookmarks": [],
        "StateOverrides": [], "Technologies": [],
        "AnkaExport": {"SkippedSourceFiles": skipped},
    }
    _atomic_json(path, payload)
    return payload
