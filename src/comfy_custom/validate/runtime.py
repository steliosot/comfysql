from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
import os
from typing import Any
from urllib import error, parse

from comfy_custom.http_auth import urlopen_with_auth_fallback


@dataclass(slots=True)
class NodeTypeSpec:
    name: str
    required_inputs: dict[str, str] = field(default_factory=dict)
    optional_inputs: dict[str, str] = field(default_factory=dict)
    required_options: dict[str, list[str]] = field(default_factory=dict)
    optional_options: dict[str, list[str]] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    output_names: list[str] = field(default_factory=list)

    @property
    def output_map(self) -> dict[str, int]:
        if self.output_names:
            return {name: idx for idx, name in enumerate(self.output_names)}
        return {f"out{idx}": idx for idx, _ in enumerate(self.outputs)}


@dataclass(slots=True)
class NodeCatalog:
    node_types: dict[str, NodeTypeSpec] = field(default_factory=dict)


@dataclass(slots=True)
class EdgeSpec:
    source_node: str
    source_output: str | int
    target_node: str
    target_input: str


@dataclass(slots=True)
class NodeSpec:
    node_id: str
    class_type: str
    inputs: dict[str, Any] = field(default_factory=dict)
    output_map: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class Graph:
    nodes: dict[str, NodeSpec] = field(default_factory=dict)
    edges: list[EdgeSpec] = field(default_factory=list)

    def add_node(self, node: NodeSpec) -> NodeSpec:
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, edge: EdgeSpec) -> EdgeSpec:
        if edge.source_node not in self.nodes:
            raise ValueError(f"Unknown source node '{edge.source_node}'")
        if edge.target_node not in self.nodes:
            raise ValueError(f"Unknown target node '{edge.target_node}'")
        self.edges.append(edge)
        return edge

    def adjacency(self) -> dict[str, list[str]]:
        adj = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            adj[edge.source_node].append(edge.target_node)
        return adj

    def reverse_adjacency(self) -> dict[str, list[str]]:
        rev = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            rev[edge.target_node].append(edge.source_node)
        return rev

    def outgoing(self, node_id: str) -> list[EdgeSpec]:
        return [edge for edge in self.edges if edge.source_node == node_id]


class GraphValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


OUTPUT_NODE_TYPES = {"SaveImage", "PreviewImage", "SaveAnimatedWEBP"}
KNOWN_LITERAL_INPUT_EXTRAS_BY_NODE = {"LoadImage": {"upload"}}
ALLOWED_VALUES_PREVIEW_LIMIT = 20

MODEL_NODE_INPUTS: list[tuple[str, str, str]] = [
    ("CheckpointLoaderSimple", "ckpt_name", "checkpoints"),
    ("LoraLoader", "lora_name", "loras"),
    ("VAELoader", "vae_name", "vae"),
    ("CLIPLoader", "clip_name", "text_encoders"),
]

ASSET_NODE_INPUTS: list[tuple[str, str, str]] = [
    ("LoadImage", "image", "input"),
    ("LoadAudio", "audio", "input"),
]


def parse_input_specs(inputs: dict[str, Any]) -> tuple[dict[str, str], dict[str, list[str]]]:
    types: dict[str, str] = {}
    options: dict[str, list[str]] = {}
    for name, spec in inputs.items():
        if isinstance(spec, list) and spec:
            type_name = spec[0]
        elif isinstance(spec, tuple) and spec:
            type_name = spec[0]
        else:
            type_name = "*"
        if isinstance(type_name, (list, tuple)):
            options[name] = [str(x) for x in type_name]
            types[name] = "ENUM"
        else:
            types[name] = str(type_name)
    return types, options


def _http_scheme() -> str:
    raw = os.environ.get("COMFY_SCHEME", "http").strip().lower()
    return raw if raw in {"http", "https"} else "http"


def build_catalog(host: str, port: int) -> NodeCatalog:
    url = f"{_http_scheme()}://{host}:{port}/object_info"
    with urlopen_with_auth_fallback(url, method="GET", timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    catalog = NodeCatalog()
    for node_name, node_payload in payload.items():
        if not isinstance(node_payload, dict):
            continue
        inputs = node_payload.get("input", {})
        required, required_options = parse_input_specs(inputs.get("required", {}))
        optional, optional_options = parse_input_specs(inputs.get("optional", {}))
        catalog.node_types[str(node_name)] = NodeTypeSpec(
            name=str(node_name),
            required_inputs=required,
            optional_inputs=optional,
            required_options=required_options,
            optional_options=optional_options,
            outputs=list(node_payload.get("output", [])),
            output_names=list(node_payload.get("output_name", [])),
        )
    return catalog


def _looks_like_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int)


def build_graph_from_api_prompt(workflow: dict[str, Any], catalog: NodeCatalog) -> Graph:
    graph = Graph()
    for node_id, node_payload in workflow.items():
        node_id_str = str(node_id)
        class_type = str(node_payload.get("class_type", ""))
        inputs_payload = node_payload.get("inputs", {})
        if not class_type or not isinstance(inputs_payload, dict):
            continue
        literal_inputs: dict[str, Any] = {}
        for input_name, value in inputs_payload.items():
            if _looks_like_link(value):
                continue
            literal_inputs[str(input_name)] = value

        node_spec = catalog.node_types.get(class_type)
        output_map = node_spec.output_map if node_spec is not None else {}
        graph.add_node(NodeSpec(node_id=node_id_str, class_type=class_type, inputs=literal_inputs, output_map=output_map))

    for node_id, node_payload in workflow.items():
        node_id_str = str(node_id)
        inputs_payload = node_payload.get("inputs", {})
        if not isinstance(inputs_payload, dict):
            continue
        for input_name, value in inputs_payload.items():
            if not _looks_like_link(value):
                continue
            graph.add_edge(
                EdgeSpec(
                    source_node=str(value[0]),
                    source_output=int(value[1]),
                    target_node=node_id_str,
                    target_input=str(input_name),
                )
            )
    return graph


def resolve_output_index(node: NodeSpec, output_name_or_idx: str | int) -> int:
    if isinstance(output_name_or_idx, int):
        return output_name_or_idx
    if output_name_or_idx in node.output_map:
        return node.output_map[output_name_or_idx]
    raise ValueError(f"Node '{node.node_id}' has no output '{output_name_or_idx}'.")


def validate_graph(graph: Graph, catalog: NodeCatalog, *, verbose_errors: bool = False) -> None:
    errors: list[str] = []
    errors.extend(_check_cycles(graph))
    errors.extend(_check_unknown_node_types(graph, catalog))
    errors.extend(_check_unknown_literal_input_keys(graph, catalog))
    errors.extend(_check_required_inputs(graph, catalog))
    errors.extend(_check_connected_to_outputs(graph))
    errors.extend(_check_duplicate_input_links(graph))
    errors.extend(_check_input_literal_link_conflicts(graph))
    errors.extend(_check_literal_value_constraints(graph, catalog, verbose_errors=verbose_errors))
    errors.extend(_check_edge_endpoints(graph, catalog))
    errors.extend(_check_edge_type_compatibility(graph, catalog))
    if errors:
        raise GraphValidationError(errors)


def _check_cycles(graph: Graph) -> list[str]:
    indegree = defaultdict(int)
    for node_id in graph.nodes:
        indegree[node_id] = 0
    for edge in graph.edges:
        indegree[edge.target_node] += 1

    queue = deque([nid for nid, deg in indegree.items() if deg == 0])
    visited = 0
    adjacency = graph.adjacency()
    while queue:
        node_id = queue.popleft()
        visited += 1
        for nxt in adjacency[node_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return ["Graph contains a cycle. Workflows must be DAGs."] if visited != len(graph.nodes) else []


def _check_unknown_node_types(graph: Graph, catalog: NodeCatalog) -> list[str]:
    out = []
    for node_id, node in graph.nodes.items():
        if node.class_type not in catalog.node_types:
            out.append(f"Node '{node_id}' uses unknown class_type '{node.class_type}'.")
    return out


def _check_required_inputs(graph: Graph, catalog: NodeCatalog) -> list[str]:
    inbound: dict[str, set[str]] = {node_id: set() for node_id in graph.nodes}
    for edge in graph.edges:
        inbound[edge.target_node].add(edge.target_input)
    out = []
    for node_id, node in graph.nodes.items():
        spec = catalog.node_types.get(node.class_type)
        if not spec:
            continue
        for input_name in spec.required_inputs:
            if input_name not in node.inputs and input_name not in inbound[node_id]:
                out.append(f"Node '{node_id}' ({node.class_type}) missing required input '{input_name}'.")
    return out


def _check_connected_to_outputs(graph: Graph) -> list[str]:
    output_nodes = [nid for nid, n in graph.nodes.items() if n.class_type in OUTPUT_NODE_TYPES]
    sink_nodes = output_nodes or [nid for nid in graph.nodes if not graph.outgoing(nid)]
    if not sink_nodes:
        return ["Graph has no sink/output node. Add at least one save/output node."]
    reverse = graph.reverse_adjacency()
    reachable: set[str] = set()
    queue = deque(sink_nodes)
    while queue:
        nid = queue.popleft()
        if nid in reachable:
            continue
        reachable.add(nid)
        for parent in reverse[nid]:
            queue.append(parent)
    disconnected = [nid for nid in graph.nodes if nid not in reachable]
    return (
        ["Disconnected nodes found (not connected to any output path): " + ", ".join(sorted(disconnected))]
        if disconnected
        else []
    )


def _check_input_literal_link_conflicts(graph: Graph) -> list[str]:
    linked: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
    for edge in graph.edges:
        linked[edge.target_node].add(edge.target_input)
    out = []
    for node_id, node in graph.nodes.items():
        for input_name in sorted(linked[node_id]):
            if input_name in node.inputs:
                out.append(f"Node '{node_id}' ({node.class_type}) input '{input_name}' is set both as literal and link.")
    return out


def _check_unknown_literal_input_keys(graph: Graph, catalog: NodeCatalog) -> list[str]:
    out = []
    for node_id, node in graph.nodes.items():
        spec = catalog.node_types.get(node.class_type)
        if not spec:
            continue
        valid = set(spec.required_inputs) | set(spec.optional_inputs)
        valid |= KNOWN_LITERAL_INPUT_EXTRAS_BY_NODE.get(node.class_type, set())
        for key in sorted(node.inputs):
            if key not in valid:
                out.append(
                    f"Node '{node_id}' ({node.class_type}) has unknown literal input '{key}'. "
                    f"Available inputs: {', '.join(sorted(valid)) if valid else '(none)'}."
                )
    return out


def _check_duplicate_input_links(graph: Graph) -> list[str]:
    inbound: dict[tuple[str, str], list[str]] = {}
    for edge in graph.edges:
        inbound.setdefault((edge.target_node, edge.target_input), []).append(f"{edge.source_node}:{edge.source_output}")
    out = []
    for (target_node, target_input), sources in sorted(inbound.items()):
        if len(sources) > 1:
            out.append(
                f"Node '{target_node}' input '{target_input}' has multiple incoming links ({', '.join(sources)})."
            )
    return out


def _check_literal_value_constraints(graph: Graph, catalog: NodeCatalog, *, verbose_errors: bool = False) -> list[str]:
    out = []
    asset_input_pairs = {(cls.lower(), inp) for cls, inp, _folder in ASSET_NODE_INPUTS}
    for node_id, node in graph.nodes.items():
        spec = catalog.node_types.get(node.class_type)
        if not spec:
            continue
        all_options = dict(spec.required_options)
        all_options.update(spec.optional_options)
        for input_name, allowed in all_options.items():
            if input_name not in node.inputs:
                continue
            if not allowed:
                # Some servers may return empty enum lists for asset pickers; defer to asset existence checks.
                continue
            value = str(node.inputs[input_name])
            allowed_set = set(allowed)
            if (node.class_type.lower(), input_name) in asset_input_pairs:
                normalized = value.replace("\\", "/").lstrip("/")
                basename = normalized.split("/")[-1] if normalized else value
                if value in allowed_set or normalized in allowed_set or basename in allowed_set:
                    continue
            elif value in allowed_set:
                continue
            if value not in allowed_set:
                out.append(
                    f"Node '{node_id}' ({node.class_type}) input '{input_name}' has invalid value '{node.inputs[input_name]}'. "
                    f"Allowed: {_format_allowed_values(allowed, verbose_errors=verbose_errors)}"
                )
        for input_name, value in node.inputs.items():
            if input_name == "steps" and (not isinstance(value, int) or value <= 0):
                out.append(f"Node '{node_id}' input 'steps' must be an integer > 0.")
            elif input_name == "cfg" and (not _is_number(value) or float(value) <= 0):
                out.append(f"Node '{node_id}' input 'cfg' must be a number > 0.")
            elif input_name == "denoise" and (not _is_number(value) or not (0.0 <= float(value) <= 1.0)):
                out.append(f"Node '{node_id}' input 'denoise' must be between 0 and 1.")
            elif input_name in {"width", "height"} and (not isinstance(value, int) or value <= 0 or value % 8 != 0):
                out.append(f"Node '{node_id}' input '{input_name}' must be a positive integer multiple of 8.")
            elif input_name == "seed" and (not isinstance(value, int) or value < 0 or value > (2**64 - 1)):
                out.append(f"Node '{node_id}' input 'seed' must be an integer in range [0, {2**64 - 1}].")
    return out


def _format_allowed_values(values: list[str], *, verbose_errors: bool) -> str:
    if verbose_errors or len(values) <= ALLOWED_VALUES_PREVIEW_LIMIT:
        return f"{', '.join(values)}."
    preview = ", ".join(values[:ALLOWED_VALUES_PREVIEW_LIMIT])
    remaining = len(values) - ALLOWED_VALUES_PREVIEW_LIMIT
    return f"{preview} ... and {remaining} more."


def _resolve_source_output_type(outputs: list[str], source_node: NodeSpec, edge: EdgeSpec) -> tuple[str | None, str | None]:
    try:
        idx = resolve_output_index(source_node, edge.source_output)
    except ValueError as exc:
        return None, str(exc)
    if idx < 0 or idx >= len(outputs):
        return None, f"Output index {idx} is out of range"
    return outputs[idx], None


def _check_edge_type_compatibility(graph: Graph, catalog: NodeCatalog) -> list[str]:
    out: list[str] = []
    for edge in graph.edges:
        source = graph.nodes[edge.source_node]
        target = graph.nodes[edge.target_node]
        source_spec = catalog.node_types.get(source.class_type)
        target_spec = catalog.node_types.get(target.class_type)
        if not source_spec or not target_spec:
            continue
        source_output_type, err = _resolve_source_output_type(source_spec.outputs, source, edge)
        if err:
            continue
        expected = target_spec.required_inputs.get(edge.target_input) or target_spec.optional_inputs.get(edge.target_input)
        if not source_output_type or not expected:
            continue
        if expected in {"*", source_output_type} or source_output_type == "*":
            continue
        out.append(
            f"Type mismatch on edge {edge.source_node}:{edge.source_output} -> {edge.target_node}:{edge.target_input}. "
            f"Got '{source_output_type}', expected '{expected}'."
        )
    return out


def _check_edge_endpoints(graph: Graph, catalog: NodeCatalog) -> list[str]:
    out: list[str] = []
    for edge in graph.edges:
        source = graph.nodes[edge.source_node]
        target = graph.nodes[edge.target_node]
        source_spec = catalog.node_types.get(source.class_type)
        target_spec = catalog.node_types.get(target.class_type)
        if not source_spec or not target_spec:
            continue
        _, err = _resolve_source_output_type(source_spec.outputs, source, edge)
        if err:
            out.append(
                f"Invalid source output on edge {edge.source_node}:{edge.source_output} -> {edge.target_node}:{edge.target_input}."
            )
        valid_inputs = sorted(set(target_spec.required_inputs) | set(target_spec.optional_inputs))
        if edge.target_input not in valid_inputs:
            out.append(
                f"Invalid target input on edge {edge.source_node}:{edge.source_output} -> {edge.target_node}:{edge.target_input}."
            )
    return out


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_json(url: str, timeout: float = 20.0) -> Any:
    with urlopen_with_auth_fallback(url, method="GET", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_model_names(payload: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                for key in ("name", "filename", "model"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        names.add(value.strip())
                        break
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                names.add(key)
            if isinstance(value, list):
                names |= _extract_model_names(value)
            elif isinstance(value, dict):
                names |= _extract_model_names(value)
    return names


def validate_model_references(host: str, port: int, graph: Graph) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    cache_by_category: dict[str, set[str] | None] = {}
    for node_id, node in graph.nodes.items():
        for class_type, input_key, category in MODEL_NODE_INPUTS:
            if node.class_type != class_type:
                continue
            value = node.inputs.get(input_key)
            if not isinstance(value, str) or not value.strip():
                continue
            model_name = value.strip()
            if category not in cache_by_category:
                try:
                    payload = _read_json(f"{_http_scheme()}://{host}:{port}/models/{category}")
                    cache_by_category[category] = _extract_model_names(payload)
                except error.HTTPError as exc:
                    # Some deployments expose /object_info and prompt APIs but block /models/*
                    # behind a separate gateway policy. In that case, keep execution usable and
                    # mark model checks as unverified instead of failing hard during validation.
                    if exc.code in {401, 403}:
                        cache_by_category[category] = None
                    else:
                        raise
            allowed = cache_by_category[category]
            exists = True if allowed is None else model_name in allowed
            record = {
                "node_id": node_id,
                "class_type": class_type,
                "input": input_key,
                "category": category,
                "model": model_name,
                "verification": "unverified_remote_models_endpoint" if allowed is None else "verified",
            }
            checked.append(record)
            if not exists:
                missing.append(record)
    return checked, missing


def validate_asset_references(host: str, port: int, graph: Graph) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for node_id, node in graph.nodes.items():
        for class_type, input_key, folder_type in ASSET_NODE_INPUTS:
            if node.class_type != class_type:
                continue
            value = node.inputs.get(input_key)
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = value.strip().replace("\\", "/").lstrip("/")
            parts = [p for p in normalized.split("/") if p]
            if not parts:
                continue
            filename = parts[-1]
            subfolder = "/".join(parts[:-1])
            query = parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
            url = f"{_http_scheme()}://{host}:{port}/view?{query}"
            exists = True
            try:
                with urlopen_with_auth_fallback(url, method="GET", timeout=15):
                    pass
            except error.HTTPError as exc:
                if exc.code == 404:
                    exists = False
                else:
                    raise
            record = {
                "node_id": node_id,
                "class_type": class_type,
                "input": input_key,
                "folder_type": folder_type,
                "asset": normalized,
            }
            checked.append(record)
            if not exists:
                missing.append(record)
    return checked, missing
