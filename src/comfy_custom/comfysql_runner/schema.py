from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import urllib.request

from comfy_custom.http_auth import build_auth_headers_from_env


PRIMITIVE_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "NUMBER"}


def _normalize_output_type_name(value: Any) -> str:
    """
    Normalize Comfy object_info output type entries.
    Some custom nodes return list-based output specs (e.g. COMBO choices)
    which are not hashable and break indexing if used directly.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "COMBO"
    if value is None:
        return "UNKNOWN"
    return str(value)


@dataclass
class InputSpec:
    name: str
    type_name: str
    required: bool
    default: Any = None
    choices: list[Any] | None = None


@dataclass
class NodeSpec:
    class_type: str
    display_name: str
    description: str
    category: str
    output_types: list[str]
    output_names: list[str]
    output_node: bool
    inputs: list[InputSpec]


class SchemaRegistry:
    def __init__(self, nodes: dict[str, NodeSpec], raw: dict[str, Any]):
        self.nodes = nodes
        self.raw = raw
        self.output_type_index = self._build_output_type_index()

    @classmethod
    def from_object_info(cls, object_info: dict[str, Any]) -> "SchemaRegistry":
        parsed: dict[str, NodeSpec] = {}

        for class_type, node_data in object_info.items():
            raw_output_types = list(node_data.get("output", []))
            output_types = [_normalize_output_type_name(v) for v in raw_output_types]
            output_names = list(node_data.get("output_name", output_types))
            input_data = node_data.get("input", {})

            inputs: list[InputSpec] = []
            for group_name, group_inputs in input_data.items():
                required = group_name == "required"
                for input_name, input_spec in group_inputs.items():
                    parsed_input = _parse_input_spec(input_name, input_spec, required)
                    inputs.append(parsed_input)

            parsed[class_type] = NodeSpec(
                class_type=class_type,
                display_name=node_data.get("display_name", class_type),
                description=node_data.get("description", ""),
                category=node_data.get("category", ""),
                output_types=output_types,
                output_names=output_names,
                output_node=bool(node_data.get("output_node", False)),
                inputs=inputs,
            )

        return cls(nodes=parsed, raw=object_info)

    def _build_output_type_index(self) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for class_type, spec in self.nodes.items():
            for out_type in spec.output_types:
                index.setdefault(out_type, []).append(class_type)
        return index

    def describe_table(self, table_name: str) -> dict[str, Any]:
        if table_name not in self.nodes:
            raise KeyError(f"Unknown table/node '{table_name}'")
        spec = self.nodes[table_name]
        return {
            "table": spec.class_type,
            "display_name": spec.display_name,
            "description": spec.description,
            "category": spec.category,
            "outputs": [
                {"name": name, "type": otype}
                for name, otype in zip(spec.output_names, spec.output_types)
            ],
            "columns": [
                {
                    "name": inp.name,
                    "type": inp.type_name,
                    "required": inp.required,
                    "default": inp.default,
                    "choices": inp.choices,
                }
                for inp in spec.inputs
            ],
        }

    def list_tables(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for class_type, spec in sorted(self.nodes.items()):
            rows.append(
                {
                    "table": class_type,
                    "display_name": spec.display_name,
                    "category": spec.category,
                    "outputs": spec.output_types,
                }
            )
        return rows


class SchemaStore:
    def __init__(self, comfy_base_url: str, cache_file: Path):
        self.comfy_base_url = comfy_base_url.rstrip("/")
        self.cache_file = cache_file
        self.registry: SchemaRegistry | None = None

    def refresh(self) -> SchemaRegistry:
        object_info = fetch_object_info(self.comfy_base_url)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(object_info, f, indent=2)
        self.registry = SchemaRegistry.from_object_info(object_info)
        return self.registry

    def load(self, prefer_cache: bool = True) -> SchemaRegistry:
        if self.registry is not None:
            return self.registry

        if prefer_cache and self.cache_file.exists():
            with self.cache_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            self.registry = SchemaRegistry.from_object_info(raw)
            return self.registry

        return self.refresh()


def fetch_object_info(comfy_base_url: str) -> dict[str, Any]:
    url = f"{comfy_base_url.rstrip('/')}/object_info"
    headers = build_auth_headers_from_env()

    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def _parse_input_spec(name: str, input_spec: Any, required: bool) -> InputSpec:
    type_name = "UNKNOWN"
    default = None
    choices = None

    if isinstance(input_spec, list) and input_spec:
        first = input_spec[0]
        meta = input_spec[1] if len(input_spec) > 1 and isinstance(input_spec[1], dict) else {}
        default = meta.get("default")

        if isinstance(first, str):
            type_name = first
        elif isinstance(first, list):
            type_name = "COMBO"
            choices = first

    elif isinstance(input_spec, str):
        type_name = input_spec

    return InputSpec(
        name=name,
        type_name=type_name,
        required=required,
        default=default,
        choices=choices,
    )


def is_connection_type(type_name: str) -> bool:
    if type_name in PRIMITIVE_TYPES:
        return False
    if type_name == "COMBO":
        return False
    return True
