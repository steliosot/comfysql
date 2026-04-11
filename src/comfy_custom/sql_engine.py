from __future__ import annotations

import copy
import json
import mimetypes
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse

from comfy_custom.http_auth import build_auth_headers_from_env, urlopen_with_auth_fallback


class SQLEngineError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


REGISTRY_SCHEMA_VERSION = 3


@dataclass
class WorkflowTableSpec:
    table: str
    workflow_path: str
    created_at: float
    kind: str = "workflow"
    default_params: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


@dataclass
class PresetSpec:
    template_name: str
    preset_name: str
    params: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass
class ProfileSpec:
    profile_name: str
    params: dict[str, Any]
    created_at: float
    updated_at: float


@dataclass
class CharacterBindingSpec:
    workflow_table: str
    character_name: str
    binding_key: str
    binding_value: Any
    created_at: float
    updated_at: float


@dataclass
class AssetAliasSpec:
    alias_name: str
    kind: str
    image_name: str
    created_at: float
    updated_at: float


@dataclass
class WorkflowSlotSpec:
    workflow_table: str
    slot_name: str
    slot_kind: str
    binding_key: str
    created_at: float
    updated_at: float


@dataclass
class WorkflowBindingAliasSpec:
    workflow_table: str
    alias: str
    raw_key: str
    class_type: str
    input_name: str
    is_primary: bool
    generated: bool
    created_at: float
    updated_at: float


@dataclass
class QueryMacroSpec:
    name: str
    sql_text: str
    created_at: float
    updated_at: float


class WorkflowRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._tables: dict[str, WorkflowTableSpec] = {}
        self._loaded = False
        self._migrated = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL registry: {exc}", exit_code=3) from exc
        if not isinstance(data, dict):
            raise SQLEngineError(f"Invalid SQL registry payload (expected object): {self.registry_path}", exit_code=3)
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )

        if version <= 1:
            tables_payload = data.get("tables", {})
            if isinstance(tables_payload, dict):
                for table, payload in tables_payload.items():
                    if not isinstance(payload, dict):
                        continue
                    self._tables[table.lower()] = WorkflowTableSpec(
                        table=str(table),
                        workflow_path=str(payload.get("workflow_path", "")),
                        created_at=float(payload.get("created_at", 0.0)),
                        kind=str(payload.get("kind", "workflow") or "workflow").lower(),
                        default_params=dict(payload.get("default_params", {}))
                        if isinstance(payload.get("default_params", {}), dict)
                        else {},
                        meta=dict(payload.get("meta", {})) if isinstance(payload.get("meta", {}), dict) else {},
                    )
            self._migrated = True
        else:
            tables_payload = data.get("tables", [])
            if isinstance(tables_payload, list):
                for row in tables_payload:
                    if not isinstance(row, dict):
                        continue
                    table = str(row.get("table", "")).strip()
                    workflow_path = str(row.get("workflow_path", "")).strip()
                    if not table or not workflow_path:
                        continue
                    self._tables[table.lower()] = WorkflowTableSpec(
                        table=table,
                        workflow_path=workflow_path,
                        created_at=float(row.get("created_at", 0.0)),
                        kind=str(row.get("kind", "workflow") or "workflow").lower(),
                        default_params=dict(row.get("default_params", {}))
                        if isinstance(row.get("default_params", {}), dict)
                        else {},
                        meta=dict(row.get("meta", {})) if isinstance(row.get("meta", {}), dict) else {},
                    )
            if version <= 2:
                self._migrated = True
        self._loaded = True
        if self._migrated:
            self.save()

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "tables": [
                {
                    "table": spec.table,
                    "workflow_path": spec.workflow_path,
                    "created_at": spec.created_at,
                    "kind": spec.kind,
                    "default_params": spec.default_params if isinstance(spec.default_params, dict) else {},
                    "meta": spec.meta if isinstance(spec.meta, dict) else {},
                }
                for spec in sorted(self._tables.values(), key=lambda s: s.table.lower())
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._migrated = False

    def create_table(
        self,
        table: str,
        workflow_path: Path,
        *,
        kind: str = "workflow",
        default_params: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> WorkflowTableSpec:
        self.load()
        key = table.lower()
        spec = WorkflowTableSpec(
            table=table,
            workflow_path=str(workflow_path),
            created_at=time.time(),
            kind=(kind or "workflow").lower(),
            default_params=dict(default_params or {}),
            meta=dict(meta or {}),
        )
        self._tables[key] = spec
        self.save()
        return spec

    def set_meta(self, table: str, meta: dict[str, Any]) -> WorkflowTableSpec | None:
        self.load()
        key = table.lower()
        spec = self._tables.get(key)
        if spec is None:
            return None
        spec.meta = dict(meta)
        self._tables[key] = spec
        self.save()
        return spec

    def unset_meta(self, table: str) -> WorkflowTableSpec | None:
        self.load()
        key = table.lower()
        spec = self._tables.get(key)
        if spec is None:
            return None
        spec.meta = {}
        self._tables[key] = spec
        self.save()
        return spec

    def drop_table(self, table: str) -> bool:
        self.load()
        key = table.lower()
        if key not in self._tables:
            return False
        del self._tables[key]
        self.save()
        return True

    def get(self, table: str) -> WorkflowTableSpec | None:
        self.load()
        return self._tables.get(table.lower())

    def list(self) -> list[WorkflowTableSpec]:
        self.load()
        return sorted(self._tables.values(), key=lambda s: s.table.lower())


class PresetRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._presets: dict[tuple[str, str], PresetSpec] = {}
        self._loaded = False
        self._migrated = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL preset registry: {exc}", exit_code=3) from exc

        if not isinstance(data, dict):
            raise SQLEngineError(f"Invalid SQL preset registry payload (expected object): {self.registry_path}", exit_code=3)
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL preset registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        if version <= 1:
            self._migrated = True

        for row in data.get("presets", []):
            if not isinstance(row, dict):
                continue
            template_name = str(row.get("template_name", ""))
            preset_name = str(row.get("preset_name", ""))
            params = row.get("params", {})
            if not template_name or not preset_name or not isinstance(params, dict):
                continue
            spec = PresetSpec(
                template_name=template_name,
                preset_name=preset_name,
                params=dict(params),
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
            self._presets[(template_name.lower(), preset_name.lower())] = spec
        self._loaded = True
        if self._migrated:
            self.save()

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "presets": [
                {
                    "template_name": spec.template_name,
                    "preset_name": spec.preset_name,
                    "params": spec.params,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(self._presets.values(), key=lambda s: (s.template_name.lower(), s.preset_name.lower()))
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._migrated = False

    def upsert(self, template_name: str, preset_name: str, params: dict[str, Any]) -> PresetSpec:
        self.load()
        now = time.time()
        key = (template_name.lower(), preset_name.lower())
        existing = self._presets.get(key)
        spec = PresetSpec(
            template_name=template_name,
            preset_name=preset_name,
            params=dict(params),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._presets[key] = spec
        self.save()
        return spec

    def delete(self, template_name: str, preset_name: str) -> bool:
        self.load()
        key = (template_name.lower(), preset_name.lower())
        if key not in self._presets:
            return False
        del self._presets[key]
        self.save()
        return True

    def get(self, template_name: str, preset_name: str) -> PresetSpec | None:
        self.load()
        return self._presets.get((template_name.lower(), preset_name.lower()))

    def list(self) -> list[PresetSpec]:
        self.load()
        return sorted(self._presets.values(), key=lambda s: (s.template_name.lower(), s.preset_name.lower()))

    def delete_for_template(self, template_name: str) -> int:
        self.load()
        key = template_name.lower()
        to_delete = [k for k in self._presets.keys() if k[0] == key]
        for item in to_delete:
            del self._presets[item]
        if to_delete:
            self.save()
        return len(to_delete)


class ProfileRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._profiles: dict[str, ProfileSpec] = {}
        self._loaded = False
        self._migrated = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL profile registry: {exc}", exit_code=3) from exc

        if not isinstance(data, dict):
            raise SQLEngineError(f"Invalid SQL profile registry payload (expected object): {self.registry_path}", exit_code=3)
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL profile registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        if version <= 1:
            self._migrated = True

        for row in data.get("profiles", []):
            if not isinstance(row, dict):
                continue
            profile_name = str(row.get("profile_name", ""))
            params = row.get("params", {})
            if not profile_name or not isinstance(params, dict):
                continue
            spec = ProfileSpec(
                profile_name=profile_name,
                params=dict(params),
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
            self._profiles[profile_name.lower()] = spec
        self._loaded = True
        if self._migrated:
            self.save()

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "profiles": [
                {
                    "profile_name": spec.profile_name,
                    "params": spec.params,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(self._profiles.values(), key=lambda s: s.profile_name.lower())
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._migrated = False

    def upsert(self, profile_name: str, params: dict[str, Any]) -> ProfileSpec:
        self.load()
        now = time.time()
        key = profile_name.lower()
        existing = self._profiles.get(key)
        spec = ProfileSpec(
            profile_name=profile_name,
            params=dict(params),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._profiles[key] = spec
        self.save()
        return spec

    def delete(self, profile_name: str) -> bool:
        self.load()
        key = profile_name.lower()
        if key not in self._profiles:
            return False
        del self._profiles[key]
        self.save()
        return True

    def get(self, profile_name: str) -> ProfileSpec | None:
        self.load()
        return self._profiles.get(profile_name.lower())

    def list(self) -> list[ProfileSpec]:
        self.load()
        return sorted(self._profiles.values(), key=lambda s: s.profile_name.lower())


class CharacterBindingRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._bindings: dict[tuple[str, str, str], CharacterBindingSpec] = {}
        self._loaded = False
        self._migrated = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL character binding registry: {exc}", exit_code=3) from exc

        if not isinstance(data, dict):
            raise SQLEngineError(
                f"Invalid SQL character binding registry payload (expected object): {self.registry_path}",
                exit_code=3,
            )
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL character binding registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        if version <= 1:
            self._migrated = True

        for row in data.get("bindings", []):
            if not isinstance(row, dict):
                continue
            workflow_table = str(row.get("workflow_table", "")).strip()
            character_name = str(row.get("character_name", "")).strip()
            binding_key = str(row.get("binding_key", "")).strip()
            if not workflow_table or not character_name or not binding_key:
                continue
            spec = CharacterBindingSpec(
                workflow_table=workflow_table,
                character_name=character_name,
                binding_key=binding_key,
                binding_value=row.get("binding_value"),
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
            self._bindings[(workflow_table.lower(), character_name.lower(), binding_key.lower())] = spec
        self._loaded = True
        if self._migrated:
            self.save()

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "bindings": [
                {
                    "workflow_table": spec.workflow_table,
                    "character_name": spec.character_name,
                    "binding_key": spec.binding_key,
                    "binding_value": spec.binding_value,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(
                    self._bindings.values(),
                    key=lambda s: (s.workflow_table.lower(), s.character_name.lower(), s.binding_key.lower()),
                )
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._migrated = False

    def upsert(
        self,
        *,
        workflow_table: str,
        character_name: str,
        binding_key: str,
        binding_value: Any,
    ) -> CharacterBindingSpec:
        self.load()
        now = time.time()
        key = (workflow_table.lower(), character_name.lower(), binding_key.lower())
        existing = self._bindings.get(key)
        spec = CharacterBindingSpec(
            workflow_table=workflow_table,
            character_name=character_name,
            binding_key=binding_key,
            binding_value=binding_value,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._bindings[key] = spec
        self.save()
        return spec

    def list(self) -> list[CharacterBindingSpec]:
        self.load()
        return sorted(
            self._bindings.values(),
            key=lambda s: (s.workflow_table.lower(), s.character_name.lower(), s.binding_key.lower()),
        )

    def list_for(self, *, workflow_table: str, character_name: str) -> list[CharacterBindingSpec]:
        self.load()
        wf = workflow_table.lower()
        ch = character_name.lower()
        out = [spec for (w, c, _), spec in self._bindings.items() if w == wf and c == ch]
        return sorted(out, key=lambda s: s.binding_key.lower())

    def has_character(self, *, character_name: str) -> bool:
        self.load()
        ch = character_name.lower()
        return any(c == ch for (_w, c, _k) in self._bindings.keys())

    def delete_for_workflow(self, workflow_table: str) -> int:
        self.load()
        wf = workflow_table.lower()
        to_delete = [k for k in self._bindings.keys() if k[0] == wf]
        for item in to_delete:
            del self._bindings[item]
        if to_delete:
            self.save()
        return len(to_delete)


class AssetAliasRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._aliases: dict[str, AssetAliasSpec] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL asset alias registry: {exc}", exit_code=3) from exc
        if not isinstance(data, dict):
            raise SQLEngineError(
                f"Invalid SQL asset alias registry payload (expected object): {self.registry_path}",
                exit_code=3,
            )
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL asset alias registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        for row in data.get("aliases", []):
            if not isinstance(row, dict):
                continue
            alias_name = str(row.get("alias_name", "")).strip()
            kind = str(row.get("kind", "")).strip().lower()
            image_name = str(row.get("image_name", "")).strip()
            if not alias_name or kind not in {"character", "object"} or not image_name:
                continue
            self._aliases[alias_name.lower()] = AssetAliasSpec(
                alias_name=alias_name,
                kind=kind,
                image_name=image_name,
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
        self._loaded = True

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "aliases": [
                {
                    "alias_name": spec.alias_name,
                    "kind": spec.kind,
                    "image_name": spec.image_name,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(self._aliases.values(), key=lambda s: s.alias_name.lower())
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert(self, *, alias_name: str, kind: str, image_name: str) -> AssetAliasSpec:
        self.load()
        now = time.time()
        key = alias_name.lower()
        existing = self._aliases.get(key)
        spec = AssetAliasSpec(
            alias_name=alias_name,
            kind=kind,
            image_name=image_name,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._aliases[key] = spec
        self.save()
        return spec

    def get(self, alias_name: str) -> AssetAliasSpec | None:
        self.load()
        return self._aliases.get(alias_name.lower())

    def list(self, *, kind: str | None = None) -> list[AssetAliasSpec]:
        self.load()
        out = list(self._aliases.values())
        if kind:
            out = [spec for spec in out if spec.kind == kind]
        return sorted(out, key=lambda s: s.alias_name.lower())


class WorkflowSlotRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._slots: dict[tuple[str, str], WorkflowSlotSpec] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL workflow slot registry: {exc}", exit_code=3) from exc
        if not isinstance(data, dict):
            raise SQLEngineError(
                f"Invalid SQL workflow slot registry payload (expected object): {self.registry_path}",
                exit_code=3,
            )
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL workflow slot registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        for row in data.get("slots", []):
            if not isinstance(row, dict):
                continue
            workflow_table = str(row.get("workflow_table", "")).strip()
            slot_name = str(row.get("slot_name", "")).strip()
            slot_kind = str(row.get("slot_kind", "")).strip().lower()
            binding_key = str(row.get("binding_key", "")).strip()
            if not workflow_table or not slot_name or slot_kind not in {"character", "object"} or not binding_key:
                continue
            self._slots[(workflow_table.lower(), slot_name.lower())] = WorkflowSlotSpec(
                workflow_table=workflow_table,
                slot_name=slot_name,
                slot_kind=slot_kind,
                binding_key=binding_key,
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
        self._loaded = True

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "slots": [
                {
                    "workflow_table": spec.workflow_table,
                    "slot_name": spec.slot_name,
                    "slot_kind": spec.slot_kind,
                    "binding_key": spec.binding_key,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(self._slots.values(), key=lambda s: (s.workflow_table.lower(), s.slot_name.lower()))
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert(self, *, workflow_table: str, slot_name: str, slot_kind: str, binding_key: str) -> WorkflowSlotSpec:
        self.load()
        now = time.time()
        key = (workflow_table.lower(), slot_name.lower())
        existing = self._slots.get(key)
        spec = WorkflowSlotSpec(
            workflow_table=workflow_table,
            slot_name=slot_name,
            slot_kind=slot_kind,
            binding_key=binding_key,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._slots[key] = spec
        self.save()
        return spec

    def list(self) -> list[WorkflowSlotSpec]:
        self.load()
        return sorted(self._slots.values(), key=lambda s: (s.workflow_table.lower(), s.slot_name.lower()))

    def list_for_workflow_kind(self, *, workflow_table: str, slot_kind: str) -> list[WorkflowSlotSpec]:
        self.load()
        wf = workflow_table.lower()
        out = [spec for (w, _s), spec in self._slots.items() if w == wf and spec.slot_kind == slot_kind]
        return sorted(out, key=lambda s: s.slot_name.lower())

    def delete_for_workflow(self, workflow_table: str) -> int:
        self.load()
        wf = workflow_table.lower()
        to_delete = [k for k in self._slots.keys() if k[0] == wf]
        for item in to_delete:
            del self._slots[item]
        if to_delete:
            self.save()
        return len(to_delete)


class WorkflowBindingAliasRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._aliases: dict[tuple[str, str], WorkflowBindingAliasSpec] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL binding alias registry: {exc}", exit_code=3) from exc
        if not isinstance(data, dict):
            raise SQLEngineError(
                f"Invalid SQL binding alias registry payload (expected object): {self.registry_path}",
                exit_code=3,
            )
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL binding alias registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        for row in data.get("aliases", []):
            if not isinstance(row, dict):
                continue
            workflow_table = str(row.get("workflow_table", "")).strip()
            alias = str(row.get("alias", "")).strip().lower()
            raw_key = str(row.get("raw_key", "")).strip().lower()
            class_type = str(row.get("class_type", "")).strip()
            input_name = str(row.get("input_name", "")).strip()
            if not workflow_table or not alias or not raw_key:
                continue
            self._aliases[(workflow_table.lower(), alias)] = WorkflowBindingAliasSpec(
                workflow_table=workflow_table,
                alias=alias,
                raw_key=raw_key,
                class_type=class_type,
                input_name=input_name,
                is_primary=bool(row.get("is_primary", False)),
                generated=bool(row.get("generated", True)),
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
        self._loaded = True

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "aliases": [
                {
                    "workflow_table": spec.workflow_table,
                    "alias": spec.alias,
                    "raw_key": spec.raw_key,
                    "class_type": spec.class_type,
                    "input_name": spec.input_name,
                    "is_primary": spec.is_primary,
                    "generated": spec.generated,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(
                    self._aliases.values(),
                    key=lambda s: (s.workflow_table.lower(), s.alias.lower()),
                )
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def replace_workflow(self, *, workflow_table: str, rows: list[WorkflowBindingAliasSpec]) -> None:
        self.load()
        wf = workflow_table.lower()
        for key in list(self._aliases.keys()):
            if key[0] == wf:
                del self._aliases[key]
        for spec in rows:
            self._aliases[(wf, spec.alias.lower())] = spec
        self.save()

    def delete_workflow(self, workflow_table: str) -> None:
        self.load()
        wf = workflow_table.lower()
        changed = False
        for key in list(self._aliases.keys()):
            if key[0] == wf:
                del self._aliases[key]
                changed = True
        if changed:
            self.save()

    def get(self, *, workflow_table: str, alias: str) -> WorkflowBindingAliasSpec | None:
        self.load()
        return self._aliases.get((workflow_table.lower(), alias.lower()))

    def list_for_workflow(self, workflow_table: str) -> list[WorkflowBindingAliasSpec]:
        self.load()
        wf = workflow_table.lower()
        out = [spec for (w, _a), spec in self._aliases.items() if w == wf]
        return sorted(out, key=lambda s: s.alias.lower())


class QueryMacroRegistry:
    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path
        self._queries: dict[str, QueryMacroSpec] = {}
        self._loaded = False
        self._migrated = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.registry_path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SQLEngineError(f"Failed to read SQL query registry: {exc}", exit_code=3) from exc
        if not isinstance(data, dict):
            raise SQLEngineError(f"Invalid SQL query registry payload (expected object): {self.registry_path}", exit_code=3)
        version = int(data.get("version", 1))
        if version > REGISTRY_SCHEMA_VERSION:
            raise SQLEngineError(
                f"SQL query registry version {version} is newer than supported {REGISTRY_SCHEMA_VERSION}.",
                exit_code=3,
            )
        if version <= 1:
            self._migrated = True
        for row in data.get("queries", []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            sql_text = str(row.get("sql_text", "")).strip()
            if not name or not sql_text:
                continue
            spec = QueryMacroSpec(
                name=name,
                sql_text=sql_text,
                created_at=float(row.get("created_at", 0.0)),
                updated_at=float(row.get("updated_at", 0.0)),
            )
            self._queries[name.lower()] = spec
        self._loaded = True
        if self._migrated:
            self.save()

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_SCHEMA_VERSION,
            "queries": [
                {
                    "name": spec.name,
                    "sql_text": spec.sql_text,
                    "created_at": spec.created_at,
                    "updated_at": spec.updated_at,
                }
                for spec in sorted(self._queries.values(), key=lambda s: s.name.lower())
            ],
        }
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._migrated = False

    def upsert(self, *, name: str, sql_text: str) -> QueryMacroSpec:
        self.load()
        now = time.time()
        key = name.lower()
        existing = self._queries.get(key)
        spec = QueryMacroSpec(
            name=name,
            sql_text=sql_text,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._queries[key] = spec
        self.save()
        return spec

    def delete(self, name: str) -> bool:
        self.load()
        key = name.lower()
        if key not in self._queries:
            return False
        del self._queries[key]
        self.save()
        return True

    def get(self, name: str) -> QueryMacroSpec | None:
        self.load()
        return self._queries.get(name.lower())

    def list(self) -> list[QueryMacroSpec]:
        self.load()
        return sorted(self._queries.values(), key=lambda s: s.name.lower())


class LocalComfySQLEngine:
    MODEL_INPUT_CATEGORY_MAP: list[tuple[str, str, str]] = [
        ("CheckpointLoaderSimple", "ckpt_name", "checkpoints"),
        ("LoraLoader", "lora_name", "loras"),
        ("VAELoader", "vae_name", "vae"),
        ("CLIPLoader", "clip_name", "text_encoders"),
        ("UNETLoader", "unet_name", "diffusion_models"),
        ("DualCLIPLoader", "clip_name1", "text_encoders"),
        ("DualCLIPLoader", "clip_name2", "text_encoders"),
        ("TripleCLIPLoader", "clip_name1", "text_encoders"),
        ("TripleCLIPLoader", "clip_name2", "text_encoders"),
        ("TripleCLIPLoader", "clip_name3", "text_encoders"),
    ]
    ASSET_UPLOAD_ENDPOINTS: dict[tuple[str, str], tuple[str, str]] = {
        ("loadimage", "image"): ("/upload/image", "image"),
        ("loadaudio", "audio"): ("/upload/audio", "audio"),
    }

    def __init__(
        self,
        *,
        comfy_dir: Path,
        state_dir: Path,
        host: str,
        port: int,
        scheme: str = "http",
        ensure_server_running: Callable[[str, int], None],
        validate_api_prompt: Callable[[dict[str, Any]], dict[str, Any]],
        submit_api_prompt: Callable[[dict[str, Any], str, int, float, bool], dict[str, Any] | None],
    ) -> None:
        self.comfy_dir = comfy_dir
        self.state_dir = state_dir
        self.host = host
        self.port = port
        self.scheme = scheme
        self._ensure_server_running = ensure_server_running
        self._validate_api_prompt_shape = validate_api_prompt
        self._submit_api_prompt = submit_api_prompt
        self.registry = WorkflowRegistry(state_dir / "sql_registry.json")
        self.preset_registry = PresetRegistry(state_dir / "sql_presets.json")
        self.profile_registry = ProfileRegistry(state_dir / "sql_profiles.json")
        self.character_binding_registry = CharacterBindingRegistry(state_dir / "sql_character_bindings.json")
        self.asset_alias_registry = AssetAliasRegistry(state_dir / "sql_asset_aliases.json")
        self.workflow_slot_registry = WorkflowSlotRegistry(state_dir / "sql_workflow_slots.json")
        self.workflow_binding_alias_registry = WorkflowBindingAliasRegistry(state_dir / "sql_binding_aliases.json")
        self.query_registry = QueryMacroRegistry(state_dir / "sql_queries.json")
        self._schema_store = None
        self._catalog = None
        self._loadimage_subfolders_supported: bool | None = None

    @property
    def comfy_base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def _auth_headers(self) -> dict[str, str]:
        return build_auth_headers_from_env()

    def _classify_failure(self, exc: Exception, *, default_category: str = "server_runtime") -> tuple[str, str]:
        message = str(exc)
        if isinstance(exc, error.HTTPError):
            if exc.code in {401, 403}:
                return ("auth", "Check COMFY_AUTH_HEADER/COMFY_AUTH_SCHEME and server auth config.")
            if exc.code in {408, 429, 502, 503, 504}:
                return ("network", "Retry shortly; verify server availability and proxy settings.")
            if exc.code == 404:
                return ("invalid_workflow", "Verify referenced endpoint/path exists on the server.")
            return (default_category, "Check server logs and endpoint compatibility.")
        if isinstance(exc, (error.URLError, TimeoutError, ConnectionError)):
            return ("network", "Check connectivity, host/port, and proxy/firewall rules.")
        low = message.lower()
        if "missing_models" in low or "missing model" in low:
            return ("missing_model", "Sync/install required models and run `sync`.")
        if "validation_failed" in low or "unknown workflow binding" in low or "invalid workflow" in low:
            return ("invalid_workflow", "Run DESCRIBE/EXPLAIN and fix field names or workflow bindings.")
        if "unauthorized" in low or "forbidden" in low:
            return ("auth", "Check auth token/header values and scope.")
        return (default_category, "Check server/runtime logs for the failing node/endpoint.")

    def _format_failure(self, *, category: str, message: str, next_action: str) -> str:
        return f"failure_category={category}; {message}; next_action={next_action}"

    def _read_json(self, path: str, timeout: float = 20.0) -> Any:
        url = f"{self.comfy_base_url}{path}"
        try:
            with urlopen_with_auth_fallback(url, method="GET", timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            category, next_action = self._classify_failure(exc, default_category="server_runtime")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=f"Failed GET {path}: {exc}",
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc

    def _read_bytes(self, path: str, timeout: float = 30.0) -> bytes:
        url = f"{self.comfy_base_url}{path}"
        try:
            with urlopen_with_auth_fallback(url, method="GET", timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            category, next_action = self._classify_failure(exc, default_category="server_runtime")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=f"Failed GET bytes {path}: {exc}",
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc

    def _list_models_inventory(self) -> list[dict[str, Any]]:
        models_url = f"{self.comfy_base_url}/models"
        try:
            with urlopen_with_auth_fallback(models_url, method="GET", timeout=20.0) as resp:
                categories = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                return self._list_models_from_object_info()
            raise SQLEngineError(f"Failed to read model categories: HTTP {exc.code}", exit_code=3) from exc
        except Exception as exc:
            raise SQLEngineError(f"Failed to read model categories: {exc}", exit_code=3) from exc

        if not isinstance(categories, list):
            raise SQLEngineError("Invalid /models response from server (expected list).", exit_code=3)

        rows: list[dict[str, Any]] = []
        for category in categories:
            if not isinstance(category, str):
                continue
            category_url = f"{self.comfy_base_url}/models/{category}"
            try:
                with urlopen_with_auth_fallback(category_url, method="GET", timeout=20.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except error.HTTPError as exc:
                if exc.code == 404:
                    continue
                if exc.code in {401, 403}:
                    # Some servers lock down specific model category endpoints.
                    continue
                raise SQLEngineError(
                    f"Failed to read models for category '{category}': HTTP {exc.code}",
                    exit_code=3,
                ) from exc
            except Exception as exc:
                raise SQLEngineError(
                    f"Failed to read models for category '{category}': {exc}",
                    exit_code=3,
                ) from exc

            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, str):
                        path = item.replace("\\", "/").strip("/")
                        filename = path.split("/")[-1] if path else item
                        folder = path.rsplit("/", 1)[0] if "/" in path else ""
                        rows.append(
                            {
                                "table": "models",
                                "kind": "model",
                                "category": category,
                                "name": filename,
                                "path": path or filename,
                                "folder": folder,
                            }
                        )
                    elif isinstance(item, dict):
                        raw_name = item.get("name") or item.get("filename") or item.get("model")
                        if not isinstance(raw_name, str) or not raw_name.strip():
                            continue
                        path = raw_name.replace("\\", "/").strip("/")
                        filename = path.split("/")[-1] if path else raw_name
                        folder = path.rsplit("/", 1)[0] if "/" in path else ""
                        rows.append(
                            {
                                "table": "models",
                                "kind": "model",
                                "category": category,
                                "name": filename,
                                "path": path or filename,
                                "folder": folder,
                            }
                        )
            elif isinstance(payload, dict):
                for key in payload.keys():
                    if not isinstance(key, str):
                        continue
                    path = key.replace("\\", "/").strip("/")
                    filename = path.split("/")[-1] if path else key
                    folder = path.rsplit("/", 1)[0] if "/" in path else ""
                    rows.append(
                        {
                            "table": "models",
                            "kind": "model",
                            "category": category,
                            "name": filename,
                            "path": path or key,
                            "folder": folder,
                        }
                    )
        return rows

    def _list_models_from_object_info(self) -> list[dict[str, Any]]:
        try:
            object_info = self._read_json("/object_info")
        except Exception as exc:
            raise SQLEngineError(
                "Failed to read /models and fallback /object_info for model inventory: "
                f"{exc}",
                exit_code=3,
            ) from exc

        if not isinstance(object_info, dict):
            raise SQLEngineError("Invalid /object_info response from server.", exit_code=3)

        seen: set[tuple[str, str]] = set()
        rows: list[dict[str, Any]] = []

        for class_type, input_name, category in self.MODEL_INPUT_CATEGORY_MAP:
            node_spec = object_info.get(class_type)
            if not isinstance(node_spec, dict):
                continue
            input_block = node_spec.get("input", {})
            if not isinstance(input_block, dict):
                continue

            widget_spec = None
            for group in ("required", "optional"):
                group_spec = input_block.get(group)
                if isinstance(group_spec, dict) and input_name in group_spec:
                    widget_spec = group_spec[input_name]
                    break
            if not (isinstance(widget_spec, list) and widget_spec):
                continue
            choices = widget_spec[0]
            if not isinstance(choices, list):
                continue

            for item in choices:
                if not isinstance(item, str) or not item.strip():
                    continue
                path = item.replace("\\", "/").strip("/")
                filename = path.split("/")[-1] if path else item
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                key = (category, path or filename)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "table": "models",
                        "kind": "model",
                        "category": category,
                        "name": filename,
                        "path": path or filename,
                        "folder": folder,
                    }
                )
        return rows

    def _load_runner_modules(self):
        try:
            from comfy_custom.comfysql_runner.planner import Planner, PlanningError
            from comfy_custom.comfysql_runner.schema import SchemaRegistry, SchemaStore, is_connection_type
            from comfy_custom.comfysql_runner.sql_parser import (
                AlterPresetQuery,
                AlterProfileQuery,
                CreateCharacterQuery,
                CreateObjectQuery,
                CreatePresetDefaultsQuery,
                CreatePresetQuery,
                CreateProfileQuery,
                CreateQueryMacroQuery,
                CreateWorkflowSlotQuery,
                CreateWorkflowTableQuery,
                DescribeQueryMacroQuery,
                DescribePresetQuery,
                DescribeProfileQuery,
                DescribeCharacterQuery,
                DescribeObjectQuery,
                DescribeQuery,
                DescribeTablesQuery,
                DropQueryMacroQuery,
                DropTableQuery,
                DropPresetQuery,
                DropProfileQuery,
                PingComfyQuery,
                RefreshSchemaQuery,
                RunQueryMacroQuery,
                SetMetaQuery,
                SQLParseError,
                SelectQuery,
                ShowQueriesQuery,
                ShowCharactersQuery,
                ShowObjectsQuery,
                UnsetMetaQuery,
                parse_sql,
            )
            from comfy_custom.comfysql_runner.templates import get_template, list_templates
        except ModuleNotFoundError as exc:
            raise SQLEngineError(
                f"ComfySQL runner modules are unavailable: {exc}. "
                "Expected under src/comfy_custom/comfysql_runner.",
                exit_code=5,
            ) from exc
        return {
            "Planner": Planner,
            "PlanningError": PlanningError,
            "SchemaRegistry": SchemaRegistry,
            "SchemaStore": SchemaStore,
            "is_connection_type": is_connection_type,
            "DescribeQuery": DescribeQuery,
            "CreatePresetDefaultsQuery": CreatePresetDefaultsQuery,
            "AlterPresetQuery": AlterPresetQuery,
            "AlterProfileQuery": AlterProfileQuery,
            "CreateCharacterQuery": CreateCharacterQuery,
            "CreateObjectQuery": CreateObjectQuery,
            "CreatePresetQuery": CreatePresetQuery,
            "CreateProfileQuery": CreateProfileQuery,
            "CreateQueryMacroQuery": CreateQueryMacroQuery,
            "CreateWorkflowSlotQuery": CreateWorkflowSlotQuery,
            "CreateWorkflowTableQuery": CreateWorkflowTableQuery,
            "DescribeQueryMacroQuery": DescribeQueryMacroQuery,
            "DescribePresetQuery": DescribePresetQuery,
            "DescribeProfileQuery": DescribeProfileQuery,
            "DescribeCharacterQuery": DescribeCharacterQuery,
            "DescribeObjectQuery": DescribeObjectQuery,
            "DescribeTablesQuery": DescribeTablesQuery,
            "DropQueryMacroQuery": DropQueryMacroQuery,
            "DropTableQuery": DropTableQuery,
            "DropPresetQuery": DropPresetQuery,
            "DropProfileQuery": DropProfileQuery,
            "PingComfyQuery": PingComfyQuery,
            "RefreshSchemaQuery": RefreshSchemaQuery,
            "RunQueryMacroQuery": RunQueryMacroQuery,
            "SetMetaQuery": SetMetaQuery,
            "SQLParseError": SQLParseError,
            "SelectQuery": SelectQuery,
            "ShowQueriesQuery": ShowQueriesQuery,
            "ShowCharactersQuery": ShowCharactersQuery,
            "ShowObjectsQuery": ShowObjectsQuery,
            "UnsetMetaQuery": UnsetMetaQuery,
            "parse_sql": parse_sql,
            "get_template": get_template,
            "list_templates": list_templates,
        }

    def _schema_store_obj(self):
        if self._schema_store is not None:
            return self._schema_store
        modules = self._load_runner_modules()
        SchemaStore = modules["SchemaStore"]
        self._schema_store = SchemaStore(
            comfy_base_url=self.comfy_base_url,
            cache_file=self.state_dir / "sql_schema_cache.json",
        )
        return self._schema_store

    def _load_schema(self):
        self._ensure_server_running(self.host, self.port)
        return self._schema_store_obj().load(prefer_cache=False)

    def _refresh_schema(self):
        self._ensure_server_running(self.host, self.port)
        self._catalog = None
        return self._schema_store_obj().refresh()

    def _resolve_workflow_path(self, raw_path: str) -> Path:
        p = Path(raw_path).expanduser()
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (Path.cwd() / p).resolve()
        if not resolved.exists():
            raise SQLEngineError(f"Workflow file not found: {resolved}", exit_code=2)
        return resolved

    def _managed_workflows_dir(self) -> Path:
        path = (self.state_dir / "workflows").resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _materialize_workflow_copy(self, *, source_path: Path, table_name: str) -> Path:
        suffix = source_path.suffix or ".json"
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in table_name) or "workflow"
        target = (self._managed_workflows_dir() / f"{safe_name}{suffix}").resolve()
        try:
            shutil.copy2(source_path, target)
        except Exception as exc:
            raise SQLEngineError(f"Failed to copy workflow into managed state folder: {exc}", exit_code=3) from exc
        return target

    def execute_sql(
        self,
        sql: str,
        *,
        compile_only: bool,
        no_cache: bool,
        timeout: float,
        statement_index: int,
        download_output: bool = False,
        download_dir: str | None = None,
        upload_mode: str = "strict",
        _macro_depth: int = 0,
    ) -> dict[str, Any]:
        modules = self._load_runner_modules()
        parse_sql = modules["parse_sql"]
        DescribeTablesQuery = modules["DescribeTablesQuery"]
        CreatePresetDefaultsQuery = modules["CreatePresetDefaultsQuery"]
        AlterPresetQuery = modules["AlterPresetQuery"]
        AlterProfileQuery = modules["AlterProfileQuery"]
        CreateCharacterQuery = modules["CreateCharacterQuery"]
        CreateObjectQuery = modules["CreateObjectQuery"]
        DescribeQuery = modules["DescribeQuery"]
        CreatePresetQuery = modules["CreatePresetQuery"]
        CreateProfileQuery = modules["CreateProfileQuery"]
        CreateQueryMacroQuery = modules["CreateQueryMacroQuery"]
        CreateWorkflowSlotQuery = modules["CreateWorkflowSlotQuery"]
        CreateWorkflowTableQuery = modules["CreateWorkflowTableQuery"]
        DescribeQueryMacroQuery = modules["DescribeQueryMacroQuery"]
        DescribePresetQuery = modules["DescribePresetQuery"]
        DescribeProfileQuery = modules["DescribeProfileQuery"]
        DescribeCharacterQuery = modules["DescribeCharacterQuery"]
        DescribeObjectQuery = modules["DescribeObjectQuery"]
        DropQueryMacroQuery = modules["DropQueryMacroQuery"]
        DropTableQuery = modules["DropTableQuery"]
        DropPresetQuery = modules["DropPresetQuery"]
        DropProfileQuery = modules["DropProfileQuery"]
        PingComfyQuery = modules["PingComfyQuery"]
        RefreshSchemaQuery = modules["RefreshSchemaQuery"]
        RunQueryMacroQuery = modules["RunQueryMacroQuery"]
        SetMetaQuery = modules["SetMetaQuery"]
        ShowQueriesQuery = modules["ShowQueriesQuery"]
        ShowCharactersQuery = modules["ShowCharactersQuery"]
        ShowObjectsQuery = modules["ShowObjectsQuery"]
        SelectQuery = modules["SelectQuery"]
        SQLParseError = modules["SQLParseError"]
        UnsetMetaQuery = modules["UnsetMetaQuery"]
        get_template = modules["get_template"]
        list_templates = modules["list_templates"]
        Planner = modules["Planner"]
        PlanningError = modules["PlanningError"]
        SchemaRegistry = modules["SchemaRegistry"]

        try:
            query = parse_sql(sql)
        except SQLParseError as exc:
            raise SQLEngineError(f"SQL parse failed: {exc}", exit_code=2) from exc

        if isinstance(query, RefreshSchemaQuery):
            schema = self._refresh_schema()
            return {"action": "refresh_schema", "tables": len(schema.nodes)}

        if isinstance(query, PingComfyQuery):
            self._ensure_server_running(self.host, self.port)
            return {"action": "ping_comfy", "reachable": True, "comfy_url": self.comfy_base_url}

        if isinstance(query, DescribeTablesQuery):
            schema = self._load_schema()
            rows: list[dict[str, Any]] = []
            rows.extend(
                {
                    "table": spec.table,
                    "kind": spec.kind,
                    "workflow_path": spec.workflow_path,
                    "default_params": spec.default_params or {},
                    "has_meta": bool(spec.meta),
                    "intent": self._workflow_intent(spec.meta or {}),
                    "signature": self._workflow_signature(spec.meta or {}),
                }
                for spec in self.registry.list()
            )
            rows.extend(
                {
                    "table": tpl.name,
                    "kind": "template",
                    "description": tpl.description,
                    "outputs": tpl.output_types,
                }
                for tpl in list_templates()
            )
            rows.extend(
                {
                    "table": row["table"],
                    "kind": "node",
                    "category": row.get("category", ""),
                    "outputs": row.get("outputs", []),
                }
                for row in schema.list_tables()
            )
            rows.extend(
                {
                    "table": f"{spec.template_name}.{spec.preset_name}",
                    "kind": "preset",
                    "template_name": spec.template_name,
                    "preset_name": spec.preset_name,
                    "updated_at": spec.updated_at,
                }
                for spec in self.preset_registry.list()
            )
            rows.extend(
                {
                    "table": spec.profile_name,
                    "kind": "profile",
                    "profile_name": spec.profile_name,
                    "updated_at": spec.updated_at,
                }
                for spec in self.profile_registry.list()
            )
            rows.append(
                {
                    "table": "models",
                    "kind": "models_table",
                    "description": "Live model inventory from /models endpoints",
                }
            )
            return {"action": "describe_tables", "rows": rows, "table_filter": getattr(query, "filter_kind", "all")}

        if isinstance(query, ShowQueriesQuery):
            rows = [
                {
                    "name": spec.name,
                    "sql_text": spec.sql_text,
                    "updated_at": spec.updated_at,
                }
                for spec in self.query_registry.list()
            ]
            return {"action": "show_queries", "rows": rows}

        if isinstance(query, ShowCharactersQuery):
            rows = self._alias_summary_rows(object_mode=False)
            return {"action": "show_characters", "rows": rows}

        if isinstance(query, ShowObjectsQuery):
            rows = self._alias_summary_rows(object_mode=True)
            return {"action": "show_objects", "rows": rows}

        if isinstance(query, DescribeCharacterQuery):
            details = self._describe_alias(alias_name=query.character_name, object_mode=False)
            details["action"] = "describe_character"
            return details

        if isinstance(query, DescribeObjectQuery):
            details = self._describe_alias(alias_name=query.object_name, object_mode=True)
            details["action"] = "describe_object"
            return details

        if isinstance(query, CreateCharacterQuery):
            spec = self.asset_alias_registry.upsert(
                alias_name=query.character_name,
                kind="character",
                image_name=query.image_name,
            )
            return {
                "action": "create_character",
                "character_name": spec.alias_name,
                "image_name": spec.image_name,
            }

        if isinstance(query, CreateObjectQuery):
            spec = self.asset_alias_registry.upsert(
                alias_name=query.object_name,
                kind="object",
                image_name=query.image_name,
            )
            return {
                "action": "create_object",
                "object_name": spec.alias_name,
                "image_name": spec.image_name,
            }

        if isinstance(query, CreateWorkflowSlotQuery):
            table_spec = self.registry.get(query.workflow_table)
            if table_spec is None:
                raise SQLEngineError(f"Workflow table '{query.workflow_table}' does not exist.", exit_code=2)
            prompt = self._load_workflow_as_api_prompt(Path(table_spec.workflow_path))
            canonical_binding_key = self._resolve_workflow_binding_key(
                workflow_table=table_spec.table,
                prompt=prompt,
                binding_key=query.binding_key,
            )
            spec = self.workflow_slot_registry.upsert(
                workflow_table=table_spec.table,
                slot_name=query.slot_name,
                slot_kind=query.slot_kind,
                binding_key=canonical_binding_key,
            )
            return {
                "action": "create_slot",
                "workflow_table": spec.workflow_table,
                "slot_name": spec.slot_name,
                "slot_kind": spec.slot_kind,
                "binding_key": spec.binding_key,
            }

        if isinstance(query, CreateQueryMacroQuery):
            spec = self.query_registry.upsert(name=query.name, sql_text=query.sql_text)
            return {"action": "create_query", "name": spec.name, "sql_text": spec.sql_text}

        if isinstance(query, DescribeQueryMacroQuery):
            spec = self.query_registry.get(query.name)
            if spec is None:
                raise SQLEngineError(f"Query '{query.name}' does not exist.", exit_code=2)
            return {
                "action": "describe_query",
                "name": spec.name,
                "sql_text": spec.sql_text,
                "created_at": spec.created_at,
                "updated_at": spec.updated_at,
            }

        if isinstance(query, DropQueryMacroQuery):
            deleted = self.query_registry.delete(query.name)
            if not deleted:
                raise SQLEngineError(f"Query '{query.name}' does not exist.", exit_code=2)
            return {"action": "drop_query", "name": query.name}

        if isinstance(query, RunQueryMacroQuery):
            if _macro_depth >= 5:
                raise SQLEngineError("Query macro recursion depth exceeded.", exit_code=2)
            spec = self.query_registry.get(query.name)
            if spec is None:
                raise SQLEngineError(f"Query '{query.name}' does not exist.", exit_code=2)
            return self.execute_sql(
                spec.sql_text,
                compile_only=compile_only,
                no_cache=no_cache,
                timeout=timeout,
                statement_index=statement_index,
                download_output=download_output,
                download_dir=download_dir,
                upload_mode=upload_mode,
                _macro_depth=_macro_depth + 1,
            )

        if isinstance(query, CreateWorkflowTableQuery):
            resolved = self._resolve_workflow_path(query.workflow_path)
            prompt = self._load_workflow_as_api_prompt(resolved)
            upload_report = None
            if not compile_only:
                mode = (upload_mode or "strict").lower()
                if mode not in {"strict", "warn", "off"}:
                    raise SQLEngineError("Invalid upload_mode. Use one of: strict, warn, off.", exit_code=2)
                if mode != "off":
                    prompt, upload_report = self._auto_upload_local_assets(prompt, timeout=timeout)
                    print(
                        f"upload_preflight uploaded={upload_report['uploaded_count']} "
                        f"skipped_existing={upload_report['skipped_existing_count']} "
                        f"failed={upload_report['failed_count']}",
                        flush=True,
                    )
                    if upload_report["failed_count"] > 0:
                        for item in upload_report.get("failed", []):
                            print(
                                f"- upload_failed local={item.get('local_path')} remote={item.get('remote_path')} "
                                f"error={item.get('error')}",
                                flush=True,
                            )
                        if mode == "strict":
                            raise SQLEngineError("Upload preflight failed; aborting workflow create.", exit_code=4)
            prompt = self._normalize_prompt_asset_paths(prompt)
            validation = self._validate_compiled_prompt(prompt)
            default_params = self._extract_workflow_default_params(prompt)
            kind = str(getattr(query, "kind", "workflow") or "workflow").lower()
            if kind not in {"workflow", "template"}:
                kind = "workflow"
            managed_workflow_path = self._materialize_workflow_copy(
                source_path=resolved,
                table_name=query.table_name,
            )
            spec = self.registry.create_table(
                query.table_name,
                managed_workflow_path,
                kind=kind,
                default_params=default_params,
                meta=self._extract_workflow_meta(resolved),
            )
            alias_specs = self._generate_binding_alias_specs(workflow_table=spec.table, prompt=prompt)
            self.workflow_binding_alias_registry.replace_workflow(workflow_table=spec.table, rows=alias_specs)
            result = {
                "action": "create_template" if kind == "template" else "create_table",
                "table": spec.table,
                "workflow_path": spec.workflow_path,
                "kind": spec.kind,
                "default_params": spec.default_params or {},
                "meta": spec.meta or {},
                "validation": validation,
            }
            if isinstance(upload_report, dict):
                result["upload_preflight"] = upload_report
            return result

        if isinstance(query, DropTableQuery):
            existing_spec = self.registry.get(query.table_name)
            dropped = self.registry.drop_table(query.table_name)
            if not dropped:
                raise SQLEngineError(f"Table '{query.table_name}' does not exist.", exit_code=2)
            self.workflow_slot_registry.delete_for_workflow(query.table_name)
            self.character_binding_registry.delete_for_workflow(query.table_name)
            self.preset_registry.delete_for_template(query.table_name)
            self.workflow_binding_alias_registry.delete_workflow(query.table_name)
            if existing_spec is not None:
                try:
                    managed_workflow_path = Path(existing_spec.workflow_path).resolve()
                    managed_root = self._managed_workflows_dir().resolve()
                    if managed_workflow_path.exists() and managed_root in managed_workflow_path.parents:
                        managed_workflow_path.unlink()
                except Exception:
                    pass
            return {"action": "drop_table", "table": query.table_name}

        if isinstance(query, SetMetaQuery):
            spec = self.registry.set_meta(query.table_name, query.meta)
            if spec is None:
                raise SQLEngineError(f"Table '{query.table_name}' does not exist.", exit_code=2)
            return {
                "action": "set_meta",
                "table": spec.table,
                "kind": spec.kind,
                "meta": spec.meta or {},
            }

        if isinstance(query, UnsetMetaQuery):
            spec = self.registry.unset_meta(query.table_name)
            if spec is None:
                raise SQLEngineError(f"Table '{query.table_name}' does not exist.", exit_code=2)
            return {
                "action": "unset_meta",
                "table": spec.table,
                "kind": spec.kind,
                "meta": spec.meta or {},
            }

        if isinstance(query, CreatePresetDefaultsQuery):
            self._ensure_template_exists(query.template_name, get_template=get_template)
            params = self._default_params_for_table_or_template(
                table_name=query.template_name,
                get_template=get_template,
            )
            spec = self.preset_registry.upsert(
                template_name=query.template_name,
                preset_name=query.preset_name,
                params=params,
            )
            return {
                "action": "create_preset",
                "template_name": spec.template_name,
                "preset_name": spec.preset_name,
                "params": spec.params,
                "from_defaults": True,
            }

        if isinstance(query, AlterPresetQuery):
            existing = self.preset_registry.get(query.template_name, query.preset_name)
            if existing is None:
                raise SQLEngineError(
                    f"Preset '{query.preset_name}' for template '{query.template_name}' does not exist.",
                    exit_code=2,
                )
            merged_params = dict(existing.params)
            merged_params.update(query.params)
            spec = self.preset_registry.upsert(
                template_name=query.template_name,
                preset_name=query.preset_name,
                params=merged_params,
            )
            return {
                "action": "alter_preset",
                "template_name": spec.template_name,
                "preset_name": spec.preset_name,
                "params": spec.params,
            }

        if isinstance(query, CreatePresetQuery):
            self._ensure_template_exists(query.template_name, get_template=get_template)
            spec = self.preset_registry.upsert(
                template_name=query.template_name,
                preset_name=query.preset_name,
                params=query.params,
            )
            return {
                "action": "create_preset",
                "template_name": spec.template_name,
                "preset_name": spec.preset_name,
                "params": spec.params,
            }

        if isinstance(query, DropPresetQuery):
            deleted = self.preset_registry.delete(
                template_name=query.template_name,
                preset_name=query.preset_name,
            )
            if not deleted:
                raise SQLEngineError(
                    f"Preset '{query.preset_name}' for template '{query.template_name}' does not exist.",
                    exit_code=2,
                )
            return {
                "action": "drop_preset",
                "template_name": query.template_name,
                "preset_name": query.preset_name,
            }

        if isinstance(query, DescribePresetQuery):
            spec = self.preset_registry.get(
                template_name=query.template_name,
                preset_name=query.preset_name,
            )
            if spec is None:
                raise SQLEngineError(
                    f"Preset '{query.preset_name}' for template '{query.template_name}' does not exist.",
                    exit_code=2,
                )
            return {
                "action": "describe_preset",
                "template_name": spec.template_name,
                "preset_name": spec.preset_name,
                "params": spec.params,
                "created_at": spec.created_at,
                "updated_at": spec.updated_at,
            }

        if isinstance(query, CreateProfileQuery):
            spec = self.profile_registry.upsert(
                profile_name=query.profile_name,
                params=query.params,
            )
            return {
                "action": "create_profile",
                "profile_name": spec.profile_name,
                "params": spec.params,
            }

        if isinstance(query, AlterProfileQuery):
            existing = self.profile_registry.get(profile_name=query.profile_name)
            if existing is None:
                raise SQLEngineError(
                    f"Profile '{query.profile_name}' does not exist.",
                    exit_code=2,
                )
            merged = dict(existing.params)
            merged.update(query.params)
            spec = self.profile_registry.upsert(
                profile_name=query.profile_name,
                params=merged,
            )
            return {
                "action": "alter_profile",
                "profile_name": spec.profile_name,
                "params": spec.params,
            }

        if isinstance(query, DropProfileQuery):
            deleted = self.profile_registry.delete(profile_name=query.profile_name)
            if not deleted:
                raise SQLEngineError(
                    f"Profile '{query.profile_name}' does not exist.",
                    exit_code=2,
                )
            return {
                "action": "drop_profile",
                "profile_name": query.profile_name,
            }

        if isinstance(query, DescribeProfileQuery):
            spec = self.profile_registry.get(profile_name=query.profile_name)
            if spec is None:
                raise SQLEngineError(
                    f"Profile '{query.profile_name}' does not exist.",
                    exit_code=2,
                )
            return {
                "action": "describe_profile",
                "profile_name": spec.profile_name,
                "params": spec.params,
                "created_at": spec.created_at,
                "updated_at": spec.updated_at,
            }

        if isinstance(query, DescribeQuery):
            if query.target.lower() == "models":
                return {
                    "action": "describe",
                    "kind": "models_table",
                    "table": "models",
                    "schema": {
                        "table": "models",
                        "description": "Live models inventory from connected server",
                        "columns": [
                            {"name": "category", "type": "STRING", "required": True},
                            {"name": "name", "type": "STRING", "required": True},
                            {"name": "path", "type": "STRING", "required": True},
                            {"name": "folder", "type": "STRING", "required": False},
                        ],
                    },
                }

            workflow_spec = self.registry.get(query.target)
            if workflow_spec is not None:
                prompt = self._load_workflow_as_api_prompt(Path(workflow_spec.workflow_path))
                bindable, ambiguous = self._workflow_bindable_fields(
                    workflow_table=workflow_spec.table,
                    prompt=prompt,
                )
                return {
                    "action": "describe",
                    "kind": workflow_spec.kind,
                    "table": workflow_spec.table,
                    "workflow_path": workflow_spec.workflow_path,
                    "default_params": workflow_spec.default_params or self._extract_workflow_default_params(prompt),
                    "meta": workflow_spec.meta or {},
                    "bindable_fields": bindable,
                    "ambiguous_fields": ambiguous,
                }

            template = get_template(query.target.lower())
            if template is not None:
                return {
                    "action": "describe",
                    "kind": "template",
                    "table": template.name,
                    "description": template.description,
                    "outputs": template.output_types,
                    "columns": [
                        {
                            "name": col.name,
                            "type": col.type_name,
                            "required": col.required,
                            "default": col.default,
                        }
                        for col in template.columns
                    ],
                }
            schema = self._load_schema()
            target = query.target
            if target not in schema.nodes:
                lowered = target.lower()
                for class_type in schema.nodes:
                    if class_type.lower() == lowered:
                        target = class_type
                        break
            try:
                node_schema = schema.describe_table(target)
            except KeyError as exc:
                raise SQLEngineError(
                    f"Unknown table/node '{query.target}'. "
                    "Use `SHOW TABLES;` to inspect available workflows, templates, and nodes.",
                    exit_code=2,
                ) from exc
            return {
                "action": "describe",
                "kind": "node",
                "table": target,
                "schema": node_schema,
            }

        if isinstance(query, SelectQuery):
            if query.table_name.lower() == "models":
                rows = self._list_models_inventory()
                filtered = self._filter_models_rows(rows, query.where, query.where_raw)
                if query.order_by is not None:
                    key, direction = query.order_by
                    allowed_order = {"category", "name", "path", "folder"}
                    if key not in allowed_order:
                        raise SQLEngineError(
                            f"Unsupported ORDER BY field '{key}' for models. Allowed: {', '.join(sorted(allowed_order))}",
                            exit_code=2,
                        )
                    reverse = direction.lower() == "desc"
                    filtered = sorted(filtered, key=lambda r: str(r.get(key, "")).lower(), reverse=reverse)
                if query.limit is not None:
                    if query.limit < 0:
                        raise SQLEngineError("LIMIT must be >= 0.", exit_code=2)
                    filtered = filtered[: query.limit]
                out_col = query.output_name.lower()
                allowed = {"category", "name", "path", "folder"}
                if out_col not in allowed:
                    raise SQLEngineError(
                        f"Unsupported SELECT column '{query.output_name}' for models. "
                        f"Allowed: {', '.join(sorted(allowed))}",
                        exit_code=2,
                    )
                return {
                    "action": "models_select",
                    "table": "models",
                    "column": out_col,
                    "count": len(filtered),
                    "rows": filtered,
                }

            workflow_spec = self.registry.get(query.table_name)
            resolved_layers: dict[str, Any] = {}
            if workflow_spec is not None:
                if query.where_raw is not None:
                    raise SQLEngineError(
                        "Advanced WHERE expressions are currently supported only for models table.",
                        exit_code=2,
                    )
                merged_where, resolved_layers = self._merge_profile_preset_character_where(
                    table_name=query.table_name,
                    preset_name=getattr(query, "preset_name", None),
                    character_name=getattr(query, "character_name", None),
                    object_name=getattr(query, "object_name", None),
                    profile_name=getattr(query, "profile_name", None),
                    where=query.where,
                )
                prompt = self._compile_workflow_table_with_alias(
                    table_spec=workflow_spec,
                    where=merged_where,
                    source_alias=getattr(query, "source_alias", None),
                )
            else:
                template = get_template(query.table_name.lower())
                schema = SchemaRegistry(nodes={}, raw={}) if template is not None else self._load_schema()
                if query.where_raw is not None:
                    raise SQLEngineError(
                        "Advanced WHERE expressions are currently supported only for models table.",
                        exit_code=2,
                    )
                merged_where, resolved_layers = self._merge_profile_preset_character_where(
                    table_name=query.table_name,
                    preset_name=getattr(query, "preset_name", None),
                    character_name=getattr(query, "character_name", None),
                    object_name=getattr(query, "object_name", None),
                    profile_name=getattr(query, "profile_name", None),
                    where=query.where,
                )
                planner = Planner(schema)
                try:
                    plan = planner.build(
                        output_name=query.output_name,
                        table_name=query.table_name,
                        where=merged_where,
                    )
                except PlanningError as exc:
                    raise SQLEngineError(f"SQL planning failed: {exc}", exit_code=2) from exc
                prompt = plan.prompt

            upload_report = None
            if not (query.explain or compile_only):
                mode = (upload_mode or "strict").lower()
                if mode not in {"strict", "warn", "off"}:
                    raise SQLEngineError("Invalid upload_mode. Use one of: strict, warn, off.", exit_code=2)
                if mode != "off":
                    prompt, upload_report = self._auto_upload_local_assets(prompt, timeout=timeout)
                    print(
                        f"upload_preflight uploaded={upload_report['uploaded_count']} "
                        f"skipped_existing={upload_report['skipped_existing_count']} "
                        f"failed={upload_report['failed_count']}",
                        flush=True,
                    )
                    if upload_report["failed_count"] > 0:
                        for item in upload_report.get("failed", []):
                            print(
                                f"- upload_failed local={item.get('local_path')} remote={item.get('remote_path')} "
                                f"error={item.get('error')}",
                                flush=True,
                            )
                        if mode == "strict":
                            raise SQLEngineError("Upload preflight failed; aborting submit.", exit_code=4)
            prompt = self._normalize_prompt_asset_paths(prompt)
            validation = self._validate_compiled_prompt(prompt)
            print(
                "validated "
                f"nodes={validation.get('nodes')} "
                f"edges={validation.get('edges')} "
                f"checked_models={len(validation.get('checked_models', []))} "
                f"checked_assets={len(validation.get('checked_assets', []))}",
                flush=True,
            )
            api_path = self._write_sql_artifact(
                statement_index=statement_index,
                stem=f"statement_{statement_index:03d}",
                payload=prompt,
            )

            if query.explain or compile_only:
                out = {
                    "action": "explain" if query.explain else "compiled",
                    "prompt": prompt,
                    "validation": validation,
                    "api_prompt_path": str(api_path),
                }
                if resolved_layers:
                    out["resolved_layers"] = resolved_layers
                return out

            submit_result = self._submit_api_prompt(prompt, self.host, self.port, timeout, no_cache) or {}
            result: dict[str, Any] = {
                "action": "select",
                "submitted": True,
                "validation": validation,
                "api_prompt_path": str(api_path),
            }
            if resolved_layers:
                result["resolved_layers"] = resolved_layers
            if isinstance(upload_report, dict):
                result["upload_preflight"] = upload_report
            prompt_id = submit_result.get("prompt_id")
            if isinstance(prompt_id, str) and prompt_id:
                result["prompt_id"] = prompt_id

            if download_output:
                if not isinstance(prompt_id, str) or not prompt_id:
                    raise SQLEngineError(
                        "download_output requested but prompt_id was not available from submit result.",
                        exit_code=4,
                    )
                local_dir = Path(download_dir).expanduser().resolve() if download_dir else (Path.cwd() / "output").resolve()
                try:
                    download_report = self._download_outputs_for_prompt(
                        prompt_id=prompt_id,
                        output_dir=local_dir,
                        timeout=timeout,
                    )
                except SQLEngineError as exc:
                    # Fallback for servers where /history is protected but /view can still be read.
                    if "failure_category=auth" in str(exc):
                        prefixes = self._extract_saveimage_prefixes(prompt)
                        if not prefixes:
                            raise
                        print(
                            "download_fallback mode=view_prefix reason=history_auth "
                            f"prefixes={','.join(prefixes)}",
                            flush=True,
                        )
                        download_report = self._download_outputs_by_prefixes(
                            prefixes=prefixes,
                            output_dir=local_dir,
                            timeout=timeout,
                        )
                    else:
                        raise
                result["downloaded_outputs"] = download_report["downloaded"]
                result["downloaded_count"] = len(download_report["downloaded"])
                result["download_failures"] = download_report["failed"]
                result["download_status"] = "ok" if not download_report["failed"] else "partial"
                result["download_dir"] = str(local_dir)
            return result

        raise SQLEngineError("Unsupported SQL command.", exit_code=2)

    def _asset_upload_endpoint_for(self, *, class_type: str, input_name: str) -> tuple[str, str]:
        key = (class_type.lower(), input_name.lower())
        return self.ASSET_UPLOAD_ENDPOINTS.get(key, ("/upload/image", "image"))

    def _map_local_asset_to_remote_path(self, local_path: Path) -> str:
        parts = list(local_path.parts)
        lowered = [p.lower() for p in parts]
        if "assets" in lowered:
            idx = lowered.index("assets")
            tail = [p for p in parts[idx + 1 :] if p]
            if tail:
                return "/".join(["assets", *tail]).replace("\\", "/")
            return f"assets/{local_path.name}"
        return local_path.name

    def _loadimage_path_mode(self) -> str:
        mode = os.environ.get("COMFY_LOADIMAGE_PATH_MODE", "auto").strip().lower()
        if mode in {"root", "preserve", "auto"}:
            return mode
        return "auto"

    def _detect_loadimage_subfolder_support(self) -> bool:
        if self._loadimage_subfolders_supported is not None:
            return self._loadimage_subfolders_supported
        try:
            object_info = self._read_json("/object_info", timeout=20.0)
            load_image = object_info.get("LoadImage", {}) if isinstance(object_info, dict) else {}
            input_block = load_image.get("input", {}) if isinstance(load_image, dict) else {}
            required = input_block.get("required", {}) if isinstance(input_block, dict) else {}
            image_spec = required.get("image")
            choices = image_spec[0] if isinstance(image_spec, list) and image_spec else None
            supports = isinstance(choices, list) and any(
                isinstance(item, str) and "/" in item.replace("\\", "/").strip("/")
                for item in choices
            )
            self._loadimage_subfolders_supported = bool(supports)
        except Exception:
            # Safe fallback for stricter servers: root filenames only.
            self._loadimage_subfolders_supported = False
        return bool(self._loadimage_subfolders_supported)

    def _select_remote_asset_path(self, *, class_type: str, input_name: str, local_path: Path) -> str:
        if class_type.lower() == "loadimage" and str(input_name).lower() == "image":
            mode = self._loadimage_path_mode()
            if mode == "root":
                return local_path.name
            if mode == "preserve":
                return self._map_local_asset_to_remote_path(local_path)
            if not self._detect_loadimage_subfolder_support():
                return local_path.name
        return self._map_local_asset_to_remote_path(local_path)

    def _resolve_local_asset_path(self, raw_value: str) -> Path | None:
        candidate = Path(raw_value).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            return resolved if resolved.exists() and resolved.is_file() else None

        normalized = raw_value.replace("\\", "/").strip().lstrip("/")
        roots: list[Path] = [Path.cwd(), self.comfy_dir, self.comfy_dir.parent]
        tried: set[Path] = set()

        def _pick(path: Path) -> Path | None:
            p = path.resolve()
            if p in tried:
                return None
            tried.add(p)
            if p.exists() and p.is_file():
                return p
            return None

        # Direct relative lookup first.
        for root in roots:
            hit = _pick(root / candidate)
            if hit is not None:
                return hit

        # assets/foo.png resolves from local input/assets first, then legacy input/.
        if normalized.lower().startswith("assets/"):
            tail = normalized.split("/", 1)[1] if "/" in normalized else candidate.name
            for root in roots:
                hit = _pick(root / "input" / "assets" / tail)
                if hit is not None:
                    return hit
            for root in roots:
                hit = _pick(root / "input" / tail)
                if hit is not None:
                    return hit

        # Bare filename like woman.jpg resolves from input/assets first (canonical),
        # then falls back to legacy input/ for backward compatibility.
        if "/" not in normalized:
            for root in roots:
                hit = _pick(root / "input" / "assets" / normalized)
                if hit is not None:
                    return hit
            for root in roots:
                hit = _pick(root / "input" / normalized)
                if hit is not None:
                    return hit

        return None

    def _remote_input_exists(self, *, filename: str, subfolder: str, timeout: float) -> bool:
        query = parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "input"})
        url = f"{self.comfy_base_url}/view?{query}"
        try:
            with urlopen_with_auth_fallback(url, method="GET", timeout=timeout):
                return True
        except error.HTTPError as exc:
            if exc.code == 404:
                return False
            category, next_action = self._classify_failure(exc, default_category="server_runtime")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=f"Failed checking existing input '{filename}' (subfolder='{subfolder}'): HTTP {exc.code}",
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc
        except Exception as exc:
            category, next_action = self._classify_failure(exc, default_category="network")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=f"Failed checking existing input '{filename}' (subfolder='{subfolder}'): {exc}",
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc

    def _build_multipart_body(
        self,
        *,
        file_field: str,
        filename: str,
        file_bytes: bytes,
        content_type: str,
        fields: dict[str, str],
    ) -> tuple[bytes, str]:
        boundary = f"----comfyagent{int(time.time() * 1000)}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            chunks.append(f"{value}\r\n".encode("utf-8"))
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(file_bytes)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), boundary

    def _upload_input_file(
        self,
        *,
        local_path: Path,
        remote_filename: str,
        remote_subfolder: str,
        endpoint: str,
        file_field: str,
        timeout: float,
    ) -> None:
        raw = local_path.read_bytes()
        ctype, _ = mimetypes.guess_type(local_path.name)
        if not ctype:
            ctype = "application/octet-stream"
        body, boundary = self._build_multipart_body(
            file_field=file_field,
            filename=remote_filename,
            file_bytes=raw,
            content_type=ctype,
            fields={
                "type": "input",
                "overwrite": "false",
                "subfolder": remote_subfolder,
            },
        )
        headers = self._auth_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        try:
            with urlopen_with_auth_fallback(
                f"{self.comfy_base_url}{endpoint}",
                method="POST",
                data=body,
                headers=headers,
                timeout=timeout,
            ):
                return
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            category, next_action = self._classify_failure(exc, default_category="server_runtime")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=(
                        f"Upload failed for '{local_path}' -> '{remote_subfolder}/{remote_filename}': "
                        f"HTTP {exc.code} {details}"
                    ),
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc
        except Exception as exc:
            category, next_action = self._classify_failure(exc, default_category="network")
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message=f"Upload failed for '{local_path}' -> '{remote_subfolder}/{remote_filename}': {exc}",
                    next_action=next_action,
                ),
                exit_code=4,
            ) from exc

    def _auto_upload_local_assets(self, prompt: dict[str, Any], *, timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
        out = copy.deepcopy(prompt)
        report: dict[str, Any] = {
            "uploaded_count": 0,
            "skipped_existing_count": 0,
            "failed_count": 0,
            "uploaded": [],
            "skipped_existing": [],
            "failed": [],
            "resolved_paths": [],
        }
        cache_by_remote: dict[str, tuple[str, str]] = {}

        asset_pairs = {
            ("loadimage", "image"),
            ("loadaudio", "audio"),
        }

        for node_id, node in out.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for input_name, value in list(inputs.items()):
                if (class_type.lower(), str(input_name).lower()) not in asset_pairs:
                    continue
                if not isinstance(value, str) or not value.strip():
                    continue
                local_path = self._resolve_local_asset_path(value)
                if local_path is None:
                    continue

                remote_path = self._select_remote_asset_path(
                    class_type=class_type,
                    input_name=str(input_name),
                    local_path=local_path,
                )
                remote_norm = remote_path.replace("\\", "/").lstrip("/")
                remote_subfolder = remote_norm.rsplit("/", 1)[0] if "/" in remote_norm else ""
                remote_filename = remote_norm.split("/")[-1]
                endpoint, file_field = self._asset_upload_endpoint_for(
                    class_type=class_type,
                    input_name=str(input_name),
                )

                status = cache_by_remote.get(remote_norm)
                if status is None:
                    try:
                        exists = self._remote_input_exists(
                            filename=remote_filename,
                            subfolder=remote_subfolder,
                            timeout=timeout,
                        )
                        if exists:
                            status = ("skipped_existing", "")
                        else:
                            self._upload_input_file(
                                local_path=local_path,
                                remote_filename=remote_filename,
                                remote_subfolder=remote_subfolder,
                                endpoint=endpoint,
                                file_field=file_field,
                                timeout=timeout,
                            )
                            status = ("uploaded", "")
                    except Exception as exc:
                        status = ("failed", str(exc))
                    cache_by_remote[remote_norm] = status

                if status[0] == "uploaded":
                    report["uploaded_count"] += 1
                    report["uploaded"].append(
                        {
                            "node_id": str(node_id),
                            "class_type": class_type,
                            "input_name": str(input_name),
                            "local_path": str(local_path),
                            "remote_path": remote_norm,
                        }
                    )
                    inputs[input_name] = remote_norm
                elif status[0] == "skipped_existing":
                    report["skipped_existing_count"] += 1
                    report["skipped_existing"].append(
                        {
                            "node_id": str(node_id),
                            "class_type": class_type,
                            "input_name": str(input_name),
                            "local_path": str(local_path),
                            "remote_path": remote_norm,
                        }
                    )
                    inputs[input_name] = remote_norm
                else:
                    report["failed_count"] += 1
                    report["failed"].append(
                        {
                            "node_id": str(node_id),
                            "class_type": class_type,
                            "input_name": str(input_name),
                            "local_path": str(local_path),
                            "remote_path": remote_norm,
                            "error": status[1],
                        }
                    )
                report["resolved_paths"].append(
                    {
                        "node_id": str(node_id),
                        "class_type": class_type,
                        "input_name": str(input_name),
                        "local_path": str(local_path),
                        "remote_path": remote_norm,
                        "status": status[0],
                    }
                )
        return out, report

    def _extract_output_file_entries(self, history_payload: Any, prompt_id: str) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        visited: set[tuple[str, str, str]] = set()

        container = history_payload
        if isinstance(history_payload, dict) and prompt_id in history_payload and isinstance(history_payload[prompt_id], dict):
            container = history_payload[prompt_id]

        outputs = container.get("outputs", {}) if isinstance(container, dict) else {}
        if not isinstance(outputs, dict):
            return records

        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for items in node_output.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    if not isinstance(filename, str) or not filename.strip():
                        continue
                    item_type = str(item.get("type", "output"))
                    if item_type != "output":
                        continue
                    subfolder = str(item.get("subfolder", "") or "")
                    key = (item_type, subfolder, filename)
                    if key in visited:
                        continue
                    visited.add(key)
                    records.append(
                        {
                            "type": item_type,
                            "subfolder": subfolder,
                            "filename": filename,
                        }
                    )
        return records

    def _download_outputs_for_prompt(self, *, prompt_id: str, output_dir: Path, timeout: float) -> dict[str, Any]:
        try:
            history_payload = self._read_json(f"/history/{parse.quote(prompt_id)}", timeout=timeout)
        except Exception as exc:
            raise SQLEngineError(f"Failed to fetch history for prompt {prompt_id}: {exc}", exit_code=4) from exc

        entries = self._extract_output_file_entries(history_payload, prompt_id=prompt_id)
        if not entries:
            return {"downloaded": [], "failed": []}

        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []
        failed: list[dict[str, Any]] = []
        for entry in entries:
            query = parse.urlencode(
                {
                    "filename": entry["filename"],
                    "subfolder": entry["subfolder"],
                    "type": entry["type"],
                }
            )
            raw: bytes | None = None
            attempts = 3
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    raw = self._read_bytes(f"/view?{query}", timeout=timeout)
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < attempts:
                        time.sleep(0.4 * attempt)
                        continue
            if raw is None:
                category, next_action = self._classify_failure(last_exc or Exception("unknown"), default_category="network")
                failed.append(
                    {
                        "filename": entry["filename"],
                        "subfolder": entry["subfolder"],
                        "error": str(last_exc) if last_exc else "unknown download error",
                        "failure_category": category,
                        "next_action": next_action,
                    }
                )
                continue

            dest_dir = output_dir / entry["subfolder"] if entry["subfolder"] else output_dir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / entry["filename"]
            if dest_path.exists():
                stem = dest_path.stem
                suffix = dest_path.suffix
                counter = 1
                while True:
                    alt = dest_dir / f"{stem}_{counter}{suffix}"
                    if not alt.exists():
                        dest_path = alt
                        break
                    counter += 1
            dest_path.write_bytes(raw)
            downloaded.append(str(dest_path))
        return {"downloaded": downloaded, "failed": failed}

    def _extract_saveimage_prefixes(self, prompt: dict[str, Any]) -> list[str]:
        prefixes: list[str] = []
        seen: set[str] = set()
        for node in prompt.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", "")).strip()
            if class_type.lower() != "saveimage":
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            raw = inputs.get("filename_prefix")
            if not isinstance(raw, str):
                continue
            value = raw.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            prefixes.append(value)
        return prefixes

    def _download_outputs_by_prefixes(
        self,
        *,
        prefixes: list[str],
        output_dir: Path,
        timeout: float,
        max_files_per_prefix: int = 1,
    ) -> dict[str, Any]:
        if not prefixes:
            return {"downloaded": [], "failed": []}
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []
        failed: list[dict[str, Any]] = []
        exts = ("png", "jpg", "jpeg", "webp")

        for prefix in prefixes:
            found_any_for_prefix = False
            for idx in range(1, max_files_per_prefix + 1):
                found_this_index = False
                for ext in exts:
                    filename = f"{prefix}_{idx:05d}_.{ext}"
                    query = parse.urlencode({"filename": filename, "subfolder": "", "type": "output"})
                    try:
                        raw = self._read_bytes(f"/view?{query}", timeout=timeout)
                    except Exception as exc:
                        text = str(exc)
                        if "HTTP Error 404" in text:
                            continue
                        category, next_action = self._classify_failure(exc, default_category="network")
                        failed.append(
                            {
                                "filename": filename,
                                "subfolder": "",
                                "error": text,
                                "failure_category": category,
                                "next_action": next_action,
                            }
                        )
                        continue

                    dest_path = output_dir / filename
                    if dest_path.exists():
                        stem = dest_path.stem
                        suffix = dest_path.suffix
                        counter = 1
                        while True:
                            alt = output_dir / f"{stem}_{counter}{suffix}"
                            if not alt.exists():
                                dest_path = alt
                                break
                            counter += 1
                    dest_path.write_bytes(raw)
                    downloaded.append(str(dest_path))
                    found_any_for_prefix = True
                    found_this_index = True
                    break
                if not found_this_index and found_any_for_prefix:
                    break
        return {"downloaded": downloaded, "failed": failed}

    def _ensure_template_exists(self, template_name: str, get_template: Callable[[str], Any]) -> None:
        if get_template(template_name.lower()) is not None:
            return
        if self.registry.get(template_name) is not None:
            return
        if template_name in self._load_schema().nodes:
            return
        lowered = template_name.lower()
        for class_type in self._load_schema().nodes:
            if class_type.lower() == lowered:
                return
        raise SQLEngineError(f"Unknown template/table '{template_name}' for preset.", exit_code=2)

    def _default_params_for_table_or_template(
        self,
        *,
        table_name: str,
        get_template: Callable[[str], Any],
    ) -> dict[str, Any]:
        workflow_spec = self.registry.get(table_name)
        if workflow_spec is not None:
            if isinstance(workflow_spec.default_params, dict) and workflow_spec.default_params:
                return dict(workflow_spec.default_params)
            prompt = self._load_workflow_as_api_prompt(Path(workflow_spec.workflow_path))
            return self._extract_workflow_default_params(prompt)

        template = get_template(table_name.lower())
        if template is not None:
            params: dict[str, Any] = {}
            for col in getattr(template, "columns", []):
                name = getattr(col, "name", None)
                default = getattr(col, "default", None)
                if not name or default is None:
                    continue
                params[str(name).lower()] = default
            return params

        # Node class fallback: no reliable static defaults in SQL layer; return empty.
        return {}

    def _extract_workflow_default_params(self, prompt: dict[str, Any]) -> dict[str, Any]:
        occurrences: dict[str, int] = {}
        node_values: list[tuple[str, str, Any]] = []

        for node_id, node in prompt.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for key, value in inputs.items():
                if self._looks_like_link(value):
                    continue
                key_str = str(key)
                occurrences[key_str] = occurrences.get(key_str, 0) + 1
                node_values.append((str(node_id), key_str, value))

        params: dict[str, Any] = {}
        for node_id, key, value in node_values:
            if occurrences.get(key, 0) == 1:
                params[key.lower()] = value
            else:
                params[f"{node_id}.{key}".lower()] = value
        return params

    @staticmethod
    def _looks_like_link(value: Any) -> bool:
        if not isinstance(value, list) or len(value) != 2:
            return False
        src, out = value
        if not isinstance(src, (str, int)):
            return False
        return isinstance(out, int)

    @staticmethod
    def _is_object_alias(name: str) -> bool:
        return str(name or "").strip().lower().startswith("obj_")

    def _alias_summary_rows(self, *, object_mode: bool) -> list[dict[str, Any]]:
        specs = self.character_binding_registry.list()
        grouped: dict[str, dict[str, Any]] = {}
        for spec in specs:
            alias = str(spec.character_name)
            if not alias:
                continue
            is_obj = self._is_object_alias(alias)
            if object_mode != is_obj:
                continue
            key = alias.lower()
            row = grouped.get(key)
            if row is None:
                row = {
                    "name": alias,
                    "kind": "object" if is_obj else "character",
                    "workflow_count": 0,
                    "binding_count": 0,
                    "workflows": set(),
                }
                grouped[key] = row
            row["binding_count"] = int(row["binding_count"]) + 1
            workflows = row.get("workflows")
            if isinstance(workflows, set):
                workflows.add(str(spec.workflow_table))
                row["workflow_count"] = len(workflows)
        out: list[dict[str, Any]] = []
        for row in grouped.values():
            workflows = sorted(str(x) for x in (row.get("workflows") or set()))
            out.append(
                {
                    "name": row.get("name"),
                    "kind": row.get("kind"),
                    "workflow_count": row.get("workflow_count", 0),
                    "binding_count": row.get("binding_count", 0),
                    "workflows": workflows,
                }
            )
        registry_kind = "object" if object_mode else "character"
        for alias in self.asset_alias_registry.list(kind=registry_kind):
            key = alias.alias_name.lower()
            if key in grouped:
                continue
            out.append(
                {
                    "name": alias.alias_name,
                    "kind": alias.kind,
                    "workflow_count": 0,
                    "binding_count": 0,
                    "workflows": [],
                    "image_name": alias.image_name,
                }
            )
        return sorted(out, key=lambda r: str(r.get("name", "")).lower())

    def _describe_alias(self, *, alias_name: str, object_mode: bool) -> dict[str, Any]:
        if not alias_name:
            raise SQLEngineError("Alias name is required.", exit_code=2)
        specs = [spec for spec in self.character_binding_registry.list() if str(spec.character_name).lower() == alias_name.lower()]
        alias_spec = self.asset_alias_registry.get(alias_name)
        if not specs and alias_spec is None:
            raise SQLEngineError(f"{'Object' if object_mode else 'Character'} '{alias_name}' does not exist.", exit_code=2)

        expected_object_mode = (alias_spec.kind == "object") if alias_spec is not None else self._is_object_alias(alias_name)
        if object_mode != expected_object_mode:
            if object_mode:
                raise SQLEngineError(
                    f"Alias '{alias_name}' is registered as a character. "
                    f"Use `DESCRIBE CHARACTER {alias_name}`.",
                    exit_code=2,
                )
            raise SQLEngineError(
                f"Alias '{alias_name}' is registered as an object. "
                f"Use `DESCRIBE OBJECT {alias_name}`.",
                exit_code=2,
            )

        bindings = [
            {
                "workflow_table": spec.workflow_table,
                "binding_key": spec.binding_key,
                "binding_value": spec.binding_value,
                "created_at": spec.created_at,
                "updated_at": spec.updated_at,
            }
            for spec in sorted(specs, key=lambda s: (s.workflow_table.lower(), s.binding_key.lower()))
        ]
        slot_bindings = [
            {
                "workflow_table": spec.workflow_table,
                "slot_name": spec.slot_name,
                "slot_kind": spec.slot_kind,
                "binding_key": spec.binding_key,
            }
            for spec in self.workflow_slot_registry.list()
            if spec.slot_kind == ("object" if object_mode else "character")
        ]
        return {
            "kind": "object" if object_mode else "character",
            "name": alias_name,
            "image_name": alias_spec.image_name if alias_spec is not None else None,
            "binding_count": len(bindings),
            "bindings": bindings,
            "slot_bindings": slot_bindings,
        }

    def upsert_character_binding(
        self,
        *,
        workflow_table: str,
        character_name: str,
        binding_key: str,
        binding_value: Any,
    ) -> CharacterBindingSpec:
        table_spec = self.registry.get(workflow_table)
        if table_spec is None:
            raise SQLEngineError(f"Unknown workflow table '{workflow_table}' for character binding.", exit_code=2)
        return self.character_binding_registry.upsert(
            workflow_table=table_spec.table,
            character_name=character_name,
            binding_key=binding_key,
            binding_value=binding_value,
        )

    def _resolve_character_params(self, *, table_name: str, character_name: str) -> dict[str, Any]:
        bindings = self.character_binding_registry.list_for(workflow_table=table_name, character_name=character_name)
        if bindings:
            out: dict[str, Any] = {}
            for spec in bindings:
                out[str(spec.binding_key).lower()] = spec.binding_value
            return out
        alias = self.asset_alias_registry.get(character_name)
        if alias is not None and alias.kind == "character":
            slots = self.workflow_slot_registry.list_for_workflow_kind(
                workflow_table=table_name,
                slot_kind="character",
            )
            if not slots:
                raise SQLEngineError(
                    f"Character '{character_name}' exists, but workflow '{table_name}' has no CHARACTER slot. "
                    "Create one with `CREATE SLOT <name> FOR <workflow> AS CHARACTER BINDING <node.input>;`.",
                    exit_code=2,
                )
            if len(slots) > 1:
                raise SQLEngineError(
                    f"Workflow '{table_name}' has multiple CHARACTER slots ({', '.join(s.slot_name for s in slots)}). "
                    "Use legacy workflow-bound character aliases for this workflow or keep a single CHARACTER slot.",
                    exit_code=2,
                )
            return {str(slots[0].binding_key).lower(): alias.image_name}
        has_character_anywhere = self.character_binding_registry.has_character(character_name=character_name)
        if has_character_anywhere:
            raise SQLEngineError(
                f"Character '{character_name}' exists but is not bound to workflow '{table_name}'. "
                "Bind it for this workflow or choose a character that is bound.",
                exit_code=2,
            )
        raise SQLEngineError(
            f"Character '{character_name}' does not exist. "
            f"Bind it first with `comfysql bind-character --workflow {table_name} --character {character_name} --image <file>`.",
            exit_code=2,
        )

    def _resolve_object_params(self, *, table_name: str, object_name: str) -> dict[str, Any]:
        alias = self.asset_alias_registry.get(object_name)
        if alias is None or alias.kind != "object":
            raise SQLEngineError(
                f"Object '{object_name}' does not exist. "
                "Create it first with `CREATE OBJECT <name> WITH image='<filename>';`.",
                exit_code=2,
            )
        slots = self.workflow_slot_registry.list_for_workflow_kind(
            workflow_table=table_name,
            slot_kind="object",
        )
        if not slots:
            raise SQLEngineError(
                f"Object '{object_name}' exists, but workflow '{table_name}' has no OBJECT slot. "
                "Create one with `CREATE SLOT <name> FOR <workflow> AS OBJECT BINDING <node.input>;`.",
                exit_code=2,
            )
        if len(slots) > 1:
            raise SQLEngineError(
                f"Workflow '{table_name}' has multiple OBJECT slots ({', '.join(s.slot_name for s in slots)}). "
                "Keep a single OBJECT slot for automatic resolution.",
                exit_code=2,
            )
        return {str(slots[0].binding_key).lower(): alias.image_name}

    def _merge_profile_preset_character_where(
        self,
        *,
        table_name: str,
        preset_name: str | None,
        character_name: str | None,
        object_name: str | None = None,
        profile_name: str | None,
        where: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        merged: dict[str, Any] = {}
        resolved_preset = preset_name
        resolved_character = character_name
        resolved_object = object_name
        resolution_hint = ""

        preset_spec = self.preset_registry.get(table_name, preset_name) if preset_name else None
        character_params: dict[str, Any] = {}

        if character_name:
            character_params = self._resolve_character_params(table_name=table_name, character_name=character_name)
        elif preset_name and preset_spec is None:
            # Backward-compatible shorthand: USING char_name.
            character_params = self._resolve_character_params(table_name=table_name, character_name=preset_name)
            resolved_character = preset_name
            resolved_preset = None
        elif preset_name:
            # Preset-first conflict behavior; explicit CHARACTER disambiguates.
            if self.character_binding_registry.list_for(workflow_table=table_name, character_name=preset_name):
                resolution_hint = (
                    f"USING '{preset_name}' resolved as preset for workflow '{table_name}'. "
                    f"Use `CHARACTER {preset_name}` to force character resolution."
                )

        if resolved_preset:
            preset = self.preset_registry.get(table_name, resolved_preset)
            if preset is None:
                raise SQLEngineError(
                    f"Preset '{resolved_preset}' for template '{table_name}' does not exist.",
                    exit_code=2,
                )
            merged = dict(preset.params)

        if character_params:
            merged.update(character_params)

        if object_name:
            merged.update(self._resolve_object_params(table_name=table_name, object_name=object_name))

        if profile_name:
            profile = self.profile_registry.get(profile_name)
            if profile is None:
                raise SQLEngineError(f"Profile '{profile_name}' does not exist.", exit_code=2)
            merged.update(profile.params)
        merged.update(where)
        merged = self._apply_cinematic_preset_fields(merged)

        resolved: dict[str, Any] = {
            "preset": resolved_preset or "",
            "character": resolved_character or "",
            "object": resolved_object or "",
            "profile": profile_name or "",
        }
        if resolution_hint:
            resolved["hint"] = resolution_hint
        return merged, resolved

    def _merge_profile_preset_where(
        self,
        *,
        table_name: str,
        preset_name: str | None,
        profile_name: str | None,
        where: dict[str, Any],
    ) -> dict[str, Any]:
        merged, _resolved = self._merge_profile_preset_character_where(
            table_name=table_name,
            preset_name=preset_name,
            character_name=None,
            object_name=None,
            profile_name=profile_name,
            where=where,
        )
        return merged

    def _merge_preset_where(self, *, table_name: str, preset_name: str | None, where: dict[str, Any]) -> dict[str, Any]:
        merged, _resolved = self._merge_profile_preset_character_where(
            table_name=table_name,
            preset_name=preset_name,
            character_name=None,
            object_name=None,
            profile_name=None,
            where=where,
        )
        return merged

    def _filter_models_rows(
        self,
        rows: list[dict[str, Any]],
        where: dict[str, Any],
        where_raw: str | None = None,
    ) -> list[dict[str, Any]]:
        if where_raw and not where:
            # Best-effort parse for models-only advanced filters.
            parsed_where: dict[str, Any] = {}
            for cond in [c.strip() for c in where_raw.split("AND") if c.strip()]:
                cm = None
                for op in ("!=", "="):
                    if op in cond:
                        left, right = cond.split(op, 1)
                        cm = (left.strip().lower(), op, right.strip().strip("'").strip('"'))
                        break
                if cm is None:
                    raise SQLEngineError(
                        "Advanced WHERE for models supports only AND with '=' or '!=' comparisons.",
                        exit_code=2,
                    )
                key, op, val = cm
                if op == "!=":
                    parsed_where[f"__neq__{key}"] = val
                else:
                    parsed_where[key] = val
            where = parsed_where
        if not where:
            return rows
        normalized_where = {str(k).lower(): v for k, v in where.items()}
        allowed = {"category", "name", "path", "folder"}
        for key in normalized_where:
            key_cmp = key[7:] if key.startswith("__neq__") else key
            if key_cmp not in allowed:
                raise SQLEngineError(
                    f"Unsupported WHERE field '{key_cmp}' for models. "
                    f"Allowed: {', '.join(sorted(allowed))}",
                    exit_code=2,
                )

        out: list[dict[str, Any]] = []
        for row in rows:
            matched = True
            for key, expected in normalized_where.items():
                neq = key.startswith("__neq__")
                target_key = key[7:] if neq else key
                actual = row.get(target_key)
                if isinstance(expected, str):
                    ok = str(actual).lower() == expected.lower()
                else:
                    ok = actual == expected
                if neq:
                    ok = not ok
                if not ok:
                    matched = False
                    break
            if matched:
                out.append(row)
        return out

    def _apply_cinematic_preset_fields(self, merged: dict[str, Any]) -> dict[str, Any]:
        out = dict(merged)

        lens_raw = out.pop("lens", None)
        camera_distance = out.pop("camera_distance", None)
        camera_angle = out.pop("camera_angle", None)
        lighting_type = out.pop("lighting_type", None)
        lighting_direction = out.pop("lighting_direction", None)
        lighting_quality = out.pop("lighting_quality", None)
        lighting_time = out.pop("lighting_time", None)

        # Lens -> default latent size, unless caller already set explicit size.
        if "width" not in out or "height" not in out:
            width_height = self._lens_default_resolution(str(lens_raw)) if lens_raw is not None else None
            if width_height is not None:
                width, height = width_height
                out.setdefault("width", width)
                out.setdefault("height", height)

        fragments: list[str] = []
        if lens_raw is not None:
            fragments.append(f"shot on {str(lens_raw)} lens")
        if camera_distance is not None:
            fragments.append(str(camera_distance))
        if camera_angle is not None:
            fragments.append(str(camera_angle))
        if lighting_type is not None:
            fragments.append(str(lighting_type))
        if lighting_direction is not None:
            fragments.append(f"lighting direction {str(lighting_direction)}")
        if lighting_quality is not None:
            fragments.append(f"{str(lighting_quality)} light")
        if lighting_time is not None:
            fragments.append(str(lighting_time))

        if fragments:
            extra = ", ".join(fragments)
            if "prompt" in out and out["prompt"]:
                out["prompt"] = f"{out['prompt']}, {extra}"
            elif "text" in out and out["text"]:
                out["text"] = f"{out['text']}, {extra}"
            else:
                out["prompt"] = extra

        return out

    def _lens_default_resolution(self, lens: str) -> tuple[int, int] | None:
        value = lens.lower().strip()
        if value.startswith("24mm"):
            return (1216, 832)  # wide composition
        if value.startswith("35mm"):
            return (1152, 896)  # natural-ish
        if value.startswith("50mm"):
            return (1024, 1024)  # standard neutral
        if value.startswith("85mm"):
            return (832, 1216)  # portrait framing
        return None

    def _write_sql_artifact(self, *, statement_index: int, stem: str, payload: dict[str, Any]) -> Path:
        run_dir = self.state_dir / "sql_runs" / f"run_{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{stem}_api_prompt.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _load_workflow_as_api_prompt(self, workflow_path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(workflow_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SQLEngineError(f"Invalid workflow JSON: {exc}", exit_code=2) from exc

        if isinstance(raw, dict) and "nodes" in raw and "links" in raw:
            return self._ui_workflow_to_api_prompt(raw)
        if isinstance(raw, dict):
            if "meta" in raw:
                raw = {k: v for k, v in raw.items() if k != "meta"}
            return self._validate_api_prompt_shape(raw)
        raise SQLEngineError("Workflow JSON must be a JSON object (UI or API format).", exit_code=2)

    def _extract_workflow_meta(self, workflow_path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(workflow_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        value = raw.get("meta")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _workflow_intent(meta: dict[str, Any]) -> str:
        value = meta.get("intent")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "-"

    @staticmethod
    def _workflow_signature(meta: dict[str, Any]) -> str:
        explicit = meta.get("signature")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        capabilities = meta.get("capabilities")
        if isinstance(capabilities, list):
            parts = [str(x).strip() for x in capabilities if str(x).strip()]
            if parts:
                return "+".join(parts[:3])

        semantics = meta.get("input_semantics")
        if isinstance(semantics, dict):
            keys = [str(k).strip() for k in semantics.keys() if str(k).strip()]
            if keys:
                return "+".join(keys[:3])
        return "-"

    def _ui_workflow_to_api_prompt(self, workflow: dict[str, Any]) -> dict[str, Any]:
        schema = self._load_schema()
        modules = self._load_runner_modules()
        is_connection_type = modules["is_connection_type"]

        links = workflow.get("links", [])
        if not isinstance(links, list):
            raise SQLEngineError("Invalid UI workflow: links must be a list.", exit_code=2)
        link_map: dict[int, list[Any]] = {}
        for item in links:
            if isinstance(item, list) and len(item) >= 5 and isinstance(item[0], int):
                link_map[item[0]] = item

        out: dict[str, Any] = {}
        nodes = workflow.get("nodes", [])
        if not isinstance(nodes, list):
            raise SQLEngineError("Invalid UI workflow: nodes must be a list.", exit_code=2)

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id"))
            class_type = str(node.get("type", ""))
            if not class_type:
                continue
            inputs: dict[str, Any] = {}

            for inp in node.get("inputs", []) if isinstance(node.get("inputs"), list) else []:
                if not isinstance(inp, dict):
                    continue
                link_id = inp.get("link")
                name = str(inp.get("name", "")).strip()
                if not name or link_id is None:
                    continue
                link = link_map.get(int(link_id))
                if link is None:
                    continue
                source_node = str(link[1])
                source_slot = int(link[2])
                inputs[name] = [source_node, source_slot]

            node_spec = schema.nodes.get(class_type)
            widget_values = node.get("widgets_values", [])
            if node_spec is not None and isinstance(widget_values, list):
                ordered_fields = list(inp.name for inp in node_spec.inputs if not is_connection_type(inp.type_name))
                assignable = [name for name in ordered_fields if name not in inputs]
                cursor = 0
                for value in widget_values:
                    if cursor >= len(assignable):
                        break
                    inputs[assignable[cursor]] = value
                    cursor += 1

            out[node_id] = {"class_type": class_type, "inputs": inputs}

        return self._validate_api_prompt_shape(out)

    def _sorted_prompt_nodes(self, prompt: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        items: list[tuple[str, dict[str, Any]]] = [
            (str(node_id), node)
            for node_id, node in prompt.items()
            if isinstance(node, dict)
        ]
        return sorted(items, key=lambda pair: (0, int(pair[0])) if pair[0].isdigit() else (1, pair[0]))

    def _build_workflow_key_indexes(
        self,
        prompt: dict[str, Any],
    ) -> tuple[dict[str, list[tuple[str, str]]], dict[tuple[str, str], str], dict[tuple[str, str], list[tuple[str, str]]]]:
        simple_key_index: dict[str, list[tuple[str, str]]] = {}
        class_type_index: dict[tuple[str, str], str] = {}
        class_input_index: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for node_id, node in prompt.items():
            inputs = node.get("inputs", {})
            class_type = str(node.get("class_type", ""))
            if not isinstance(inputs, dict):
                continue
            for key in inputs.keys():
                simple_key_index.setdefault(str(key), []).append((str(node_id), str(key)))
                class_type_index[(str(node_id), str(key))] = class_type
                if class_type:
                    class_input_index.setdefault((class_type.lower(), str(key)), []).append((str(node_id), str(key)))
        return simple_key_index, class_type_index, class_input_index

    def _generate_binding_alias_specs(self, *, workflow_table: str, prompt: dict[str, Any]) -> list[WorkflowBindingAliasSpec]:
        now = time.time()
        used_aliases: set[str] = set()
        specs: list[WorkflowBindingAliasSpec] = []
        counters: dict[str, int] = {}

        def register_alias(base: str, *, node_id: str, class_type: str, input_name: str) -> None:
            alias = base
            suffix = 2
            while alias in used_aliases:
                alias = f"{base}_{suffix}"
                suffix += 1
            used_aliases.add(alias)
            specs.append(
                WorkflowBindingAliasSpec(
                    workflow_table=workflow_table,
                    alias=alias,
                    raw_key=f"{node_id}.{input_name}".lower(),
                    class_type=class_type,
                    input_name=input_name,
                    is_primary=(alias == base),
                    generated=True,
                    created_at=now,
                    updated_at=now,
                )
            )

        for node_id, node in self._sorted_prompt_nodes(prompt):
            inputs = node.get("inputs", {})
            class_type = str(node.get("class_type", ""))
            class_key = class_type.lower()
            if not isinstance(inputs, dict):
                continue

            if class_key == "loadimage" and "image" in inputs:
                idx = counters.get("loadimage", 0) + 1
                counters["loadimage"] = idx
                if idx == 1:
                    base = "subject_image"
                elif idx == 2:
                    base = "reference_image"
                else:
                    base = f"reference_image_{idx - 1}"
                register_alias(base, node_id=node_id, class_type=class_type, input_name="image")

            if class_key == "cliptextencode" and "text" in inputs:
                idx = counters.get("cliptextencode_text", 0) + 1
                counters["cliptextencode_text"] = idx
                if idx == 1:
                    base = "prompt"
                elif idx == 2:
                    base = "negative_prompt"
                else:
                    base = f"prompt_{idx - 1}"
                register_alias(base, node_id=node_id, class_type=class_type, input_name="text")

            if class_key in {"ksampler", "ksampleradvanced"}:
                for input_name in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
                    if input_name in inputs:
                        register_alias(input_name, node_id=node_id, class_type=class_type, input_name=input_name)

            if class_key in {"emptylatentimage", "emptysd3latentimage", "emptysdxllatentimage"}:
                for input_name in ("width", "height", "batch_size"):
                    if input_name in inputs:
                        register_alias(input_name, node_id=node_id, class_type=class_type, input_name=input_name)

            if class_key == "saveimage" and "filename_prefix" in inputs:
                register_alias("filename_prefix", node_id=node_id, class_type=class_type, input_name="filename_prefix")

            for input_name in ("ckpt_name", "unet_name", "clip_name", "vae_name"):
                if input_name in inputs:
                    register_alias(input_name, node_id=node_id, class_type=class_type, input_name=input_name)

        return specs

    def _ensure_workflow_binding_aliases(self, *, workflow_table: str, prompt: dict[str, Any]) -> list[WorkflowBindingAliasSpec]:
        existing = self.workflow_binding_alias_registry.list_for_workflow(workflow_table)
        if existing:
            return existing
        generated = self._generate_binding_alias_specs(workflow_table=workflow_table, prompt=prompt)
        self.workflow_binding_alias_registry.replace_workflow(workflow_table=workflow_table, rows=generated)
        return generated

    def _workflow_bindable_fields(self, *, workflow_table: str, prompt: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        occurrences: dict[str, int] = {}
        for _node_id, node in prompt.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for key, value in inputs.items():
                if isinstance(value, list) and len(value) == 2:
                    continue
                occurrences[str(key)] = occurrences.get(str(key), 0) + 1

        ambiguous_fields = sorted({k for k, count in occurrences.items() if count > 1})
        aliases = self._ensure_workflow_binding_aliases(workflow_table=workflow_table, prompt=prompt)
        bindable_fields = [
            {
                "alias": spec.alias,
                "raw_key": spec.raw_key,
                "class_type": spec.class_type,
                "input_name": spec.input_name,
                "is_primary": spec.is_primary,
                "generated": spec.generated,
            }
            for spec in aliases
        ]
        return bindable_fields, ambiguous_fields

    def _compile_workflow_table(self, *, table_spec: WorkflowTableSpec, where: dict[str, Any]) -> dict[str, Any]:
        return self._compile_workflow_table_with_alias(table_spec=table_spec, where=where, source_alias=None)

    def _compile_workflow_table_with_alias(
        self,
        *,
        table_spec: WorkflowTableSpec,
        where: dict[str, Any],
        source_alias: str | None,
    ) -> dict[str, Any]:
        prompt = self._load_workflow_as_api_prompt(Path(table_spec.workflow_path))
        patched = json.loads(json.dumps(prompt))
        simple_key_index, class_type_index, class_input_index = self._build_workflow_key_indexes(patched)
        alias_specs = self._ensure_workflow_binding_aliases(workflow_table=table_spec.table, prompt=patched)
        alias_map = {spec.alias.lower(): spec.raw_key.lower() for spec in alias_specs}

        for key, value in where.items():
            raw_key = str(key)
            normalized_key = self._strip_source_prefix(raw_key, table_name=table_spec.table, source_alias=source_alias)
            if "." not in normalized_key and normalized_key not in simple_key_index:
                alias_raw = alias_map.get(normalized_key.lower())
                if alias_raw:
                    normalized_key = alias_raw
            if "." in normalized_key:
                left, input_name = normalized_key.split(".", 1)
                node_payload = patched.get(left)
                if not isinstance(node_payload, dict):
                    class_targets = class_input_index.get((left.lower(), input_name), [])
                    if len(class_targets) == 1:
                        node_id, scoped_input = class_targets[0]
                        class_type = class_type_index.get((node_id, scoped_input), "")
                        patched[node_id]["inputs"][scoped_input] = self._normalize_asset_binding_value(
                            class_type=class_type,
                            input_name=scoped_input,
                            value=value,
                        )
                        continue
                    if len(class_targets) > 1:
                        raise SQLEngineError(
                            f"Ambiguous class binding '{raw_key}' for table '{table_spec.table}'. "
                            "Use node_id.input_name form.",
                            exit_code=2,
                        )
                else:
                    inputs = node_payload.get("inputs", {})
                    if not isinstance(inputs, dict) or input_name not in inputs:
                        raise SQLEngineError(
                            f"Unknown input '{raw_key}' for workflow table '{table_spec.table}'.",
                            exit_code=2,
                        )
                    class_type = str(node_payload.get("class_type", ""))
                    inputs[input_name] = self._normalize_asset_binding_value(
                        class_type=class_type,
                        input_name=input_name,
                        value=value,
                    )
                    continue

            targets = simple_key_index.get(normalized_key, [])
            if not targets:
                targets = self._semantic_targets(
                    key=normalized_key,
                    simple_key_index=simple_key_index,
                    class_type_index=class_type_index,
                )
            if not targets:
                raise SQLEngineError(
                    f"Unknown workflow binding '{raw_key}' for table '{table_spec.table}'. "
                    "Use DESCRIBE <table> to see bindable fields.",
                    exit_code=2,
                )
            if len(targets) > 1:
                narrowed = self._prefer_target(targets, class_type_index=class_type_index, key=normalized_key)
                if narrowed is None:
                    raise SQLEngineError(
                        f"Ambiguous workflow binding '{raw_key}' for table '{table_spec.table}'. "
                        "Use node_id.input_name form.",
                        exit_code=2,
                    )
                targets = [narrowed]
            node_id, input_name = targets[0]
            class_type = class_type_index.get((node_id, input_name), "")
            patched[node_id]["inputs"][input_name] = self._normalize_asset_binding_value(
                class_type=class_type,
                input_name=input_name,
                value=value,
            )

        return self._validate_api_prompt_shape(patched)

    def _normalize_prompt_asset_paths(self, prompt: dict[str, Any]) -> dict[str, Any]:
        for _node_id, node in prompt.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for input_name, value in list(inputs.items()):
                inputs[input_name] = self._normalize_asset_binding_value(
                    class_type=class_type,
                    input_name=str(input_name),
                    value=value,
                )
        return prompt

    def _normalize_asset_binding_value(self, *, class_type: str, input_name: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized_class = class_type.lower()
        normalized_input = input_name.lower()
        asset_pairs = {
            ("loadimage", "image"),
            ("loadaudio", "audio"),
        }
        if (normalized_class, normalized_input) not in asset_pairs:
            return value
        trimmed = value.strip().replace("\\", "/")
        if not trimmed:
            return value
        return trimmed.lstrip("/")

    def _strip_source_prefix(self, key: str, *, table_name: str, source_alias: str | None) -> str:
        if "." not in key:
            return key
        first, rest = key.split(".", 1)
        if source_alias and first.lower() == source_alias.lower():
            return rest
        if first.lower() == table_name.lower():
            return rest
        return key

    def _resolve_workflow_binding_key(self, *, workflow_table: str, prompt: dict[str, Any], binding_key: str) -> str:
        normalized = str(binding_key or "").strip().lower()
        if not normalized:
            raise SQLEngineError("Slot binding key cannot be empty.", exit_code=2)

        simple_key_index, _class_type_index, _class_input_index = self._build_workflow_key_indexes(prompt)
        if "." in normalized:
            node_id, input_name = normalized.split(".", 1)
            node = prompt.get(node_id)
            if isinstance(node, dict):
                inputs = node.get("inputs", {})
                if isinstance(inputs, dict) and input_name in inputs:
                    return normalized
            raise SQLEngineError(
                f"Unknown workflow binding '{binding_key}' for workflow '{workflow_table}'. "
                "Use DESCRIBE WORKFLOW to see bindable fields.",
                exit_code=2,
            )

        self._ensure_workflow_binding_aliases(workflow_table=workflow_table, prompt=prompt)
        alias_spec = self.workflow_binding_alias_registry.get(workflow_table=workflow_table, alias=normalized)
        if alias_spec is not None:
            return alias_spec.raw_key.lower()

        candidates = simple_key_index.get(normalized, [])
        if len(candidates) == 1:
            node_id, input_name = candidates[0]
            return f"{node_id}.{input_name}".lower()
        if len(candidates) > 1:
            raise SQLEngineError(
                f"Ambiguous workflow binding '{binding_key}' for workflow '{workflow_table}'. "
                "Use alias name or node_id.input_name form.",
                exit_code=2,
            )
        raise SQLEngineError(
            f"Unknown workflow binding '{binding_key}' for workflow '{workflow_table}'. "
            "Use DESCRIBE WORKFLOW to see bindable fields.",
            exit_code=2,
        )

    def _semantic_targets(
        self,
        *,
        key: str,
        simple_key_index: dict[str, list[tuple[str, str]]],
        class_type_index: dict[tuple[str, str], str],
    ) -> list[tuple[str, str]]:
        aliases: dict[str, list[str]] = {
            "seed": ["seed", "noise_seed"],
            "prompt": ["text", "prompt"],
            "negative_prompt": ["negative_prompt", "text_negative"],
            "checkpoint": ["ckpt_name", "checkpoint"],
            "input_image": ["image", "input_image"],
            "sampler": ["sampler_name", "sampler"],
        }
        out: list[tuple[str, str]] = []
        for candidate in aliases.get(key, []):
            out.extend(simple_key_index.get(candidate, []))
        # De-duplicate while preserving order.
        dedup: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in out:
            if item in seen:
                continue
            seen.add(item)
            dedup.append(item)
        return dedup

    def _prefer_target(
        self,
        targets: list[tuple[str, str]],
        *,
        class_type_index: dict[tuple[str, str], str],
        key: str,
    ) -> tuple[str, str] | None:
        def score(item: tuple[str, str]) -> tuple[int, int]:
            node_id, input_name = item
            class_type = class_type_index.get((node_id, input_name), "")
            id_int = int(node_id) if node_id.isdigit() else 999999

            # Lower score is better.
            bonus = 5
            if key in {"seed", "sampler", "cfg", "steps", "denoise"} and class_type in {"KSampler", "KSamplerAdvanced"}:
                bonus = 0
            elif key in {"prompt", "negative_prompt", "text"} and class_type == "CLIPTextEncode":
                bonus = 1
            elif key in {"checkpoint"} and class_type in {"CheckpointLoaderSimple", "CheckpointLoader"}:
                bonus = 0
            elif key in {"input_image"} and class_type == "LoadImage":
                bonus = 0
            return (bonus, id_int)

        ranked = sorted(targets, key=score)
        if not ranked:
            return None
        # For negative prompt try second CLIPTextEncode if available.
        if key == "negative_prompt":
            clip_targets = [item for item in ranked if class_type_index.get(item) == "CLIPTextEncode"]
            if len(clip_targets) >= 2:
                return clip_targets[1]
        return ranked[0]

    def _validate_compiled_prompt(self, prompt: dict[str, Any]) -> dict[str, Any]:
        self._ensure_server_running(self.host, self.port)
        from comfy_custom.validate.runtime import (
            GraphValidationError,
            validate_asset_references,
            validate_graph,
            validate_model_references,
        )

        catalog = self._get_catalog()
        graph = self._graph_from_api_prompt(prompt, catalog)

        try:
            validate_graph(graph, catalog, verbose_errors=False)
        except GraphValidationError as exc:
            formatted = "; ".join(exc.errors[:5])
            raise SQLEngineError(f"validation_failed: {formatted}", exit_code=2) from exc

        checked_models, missing_models = validate_model_references(self.host, self.port, graph)
        checked_assets, missing_assets = validate_asset_references(self.host, self.port, graph)
        if missing_models or missing_assets:
            parts: list[str] = []
            if missing_models:
                parts.append(f"missing_models={len(missing_models)}")
            if missing_assets:
                parts.append(f"missing_assets={len(missing_assets)}")
            category = "missing_model" if missing_models else "invalid_workflow"
            next_action = (
                "Run `comfy-agent sync` and verify model names in workflow/presets."
                if missing_models
                else "Ensure input assets exist on the server input path."
            )
            raise SQLEngineError(
                self._format_failure(
                    category=category,
                    message="validation_failed: " + ", ".join(parts),
                    next_action=next_action,
                ),
                exit_code=2,
            )
        return {
            "status": "ok",
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "checked_models": checked_models,
            "checked_assets": checked_assets,
        }

    def _get_catalog(self):
        if self._catalog is not None:
            return self._catalog
        from comfy_custom.validate.runtime import build_catalog

        self._catalog = build_catalog(self.host, self.port)
        return self._catalog

    def _graph_from_api_prompt(self, workflow: dict[str, Any], catalog):
        from comfy_custom.validate.runtime import build_graph_from_api_prompt

        try:
            return build_graph_from_api_prompt(workflow, catalog)
        except ValueError as exc:
            raise SQLEngineError(str(exc), exit_code=2) from exc
