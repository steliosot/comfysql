from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import InputSpec, SchemaRegistry, is_connection_type
from .templates import get_template


class PlanningError(ValueError):
    pass


NodeOutputRef = tuple[str, int]


@dataclass
class PlanResult:
    prompt: dict[str, Any]
    output_node_id: str
    output_slot: int
    trace: list[str]


MODEL_PROFILES = [
    {
        "contains": "juggernaut_reborn",
        "defaults": {
            "steps": 20,
            "cfg": 8.0,
            "sampler": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
        },
    }
]

DEFAULT_TYPE_PROVIDERS: dict[str, tuple[str, int]] = {
    "MODEL": ("CheckpointLoaderSimple", 0),
    "CLIP": ("CheckpointLoaderSimple", 1),
    "VAE": ("CheckpointLoaderSimple", 2),
    "IMAGE": ("LoadImage", 0),
    "LATENT": ("EmptyLatentImage", 0),
    "CONDITIONING": ("CLIPTextEncode", 0),
}


class PromptGraph:
    def __init__(self) -> None:
        self.prompt: dict[str, Any] = {}
        self.counter = 1

    def add_node(self, class_type: str, inputs: dict[str, Any]) -> str:
        node_id = str(self.counter)
        self.counter += 1
        self.prompt[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
        }
        return node_id


def _model_defaults(checkpoint: str) -> dict[str, Any]:
    checkpoint_lower = checkpoint.lower()
    for profile in MODEL_PROFILES:
        if profile["contains"] in checkpoint_lower:
            return dict(profile["defaults"])
    return {}


def _coalesce(where: dict[str, Any], key: str, default: Any) -> Any:
    return where.get(key, default)


class Planner:
    def __init__(self, schema: SchemaRegistry):
        self.schema = schema

    def build(self, output_name: str, table_name: str, where: dict[str, Any]) -> PlanResult:
        template = get_template(table_name.lower())
        if template is not None:
            return self._build_template_img2img(output_name, where)

        return self._build_dynamic(output_name, table_name, where)

    def _build_template_img2img(self, output_name: str, where: dict[str, Any]) -> PlanResult:
        if output_name != "image":
            raise PlanningError("Template img2img_process currently supports only SELECT image")

        if "checkpoint" not in where:
            raise PlanningError("img2img_process requires checkpoint in WHERE clause")
        if "prompt" not in where:
            raise PlanningError("img2img_process requires prompt in WHERE clause")

        graph = PromptGraph()
        trace: list[str] = []

        checkpoint = str(where["checkpoint"])
        profile_defaults = _model_defaults(checkpoint)

        ckpt = graph.add_node("CheckpointLoaderSimple", {"ckpt_name": checkpoint})
        trace.append(f"Added CheckpointLoaderSimple ({ckpt})")

        positive = graph.add_node(
            "CLIPTextEncode",
            {
                "clip": [ckpt, 1],
                "text": str(where["prompt"]),
            },
        )
        negative = graph.add_node(
            "CLIPTextEncode",
            {
                "clip": [ckpt, 1],
                "text": str(_coalesce(where, "negative_prompt", "")),
            },
        )
        trace.append(f"Added CLIPTextEncode nodes ({positive}, {negative})")

        input_image = where.get("input_image")
        if input_image:
            load_image = graph.add_node(
                "LoadImage",
                {
                    "image": str(input_image),
                    "upload": "image",
                },
            )
            latent_source = graph.add_node(
                "VAEEncode",
                {
                    "pixels": [load_image, 0],
                    "vae": [ckpt, 2],
                },
            )
            trace.append(f"Using img2img branch: LoadImage ({load_image}) -> VAEEncode ({latent_source})")
        else:
            latent_source = graph.add_node(
                "EmptyLatentImage",
                {
                    "width": int(_coalesce(where, "width", 1024)),
                    "height": int(_coalesce(where, "height", 1024)),
                    "batch_size": int(_coalesce(where, "batch_size", 1)),
                },
            )
            trace.append(f"Using txt2img branch: EmptyLatentImage ({latent_source})")

        ksampler = graph.add_node(
            "KSampler",
            {
                "model": [ckpt, 0],
                "positive": [positive, 0],
                "negative": [negative, 0],
                "latent_image": [latent_source, 0],
                "seed": int(_coalesce(where, "seed", 0)),
                "steps": int(_coalesce(where, "steps", profile_defaults.get("steps", 20))),
                "cfg": float(_coalesce(where, "cfg", profile_defaults.get("cfg", 8.0))),
                "sampler_name": str(_coalesce(where, "sampler", profile_defaults.get("sampler", "euler"))),
                "scheduler": str(_coalesce(where, "scheduler", profile_defaults.get("scheduler", "normal"))),
                "denoise": float(_coalesce(where, "denoise", profile_defaults.get("denoise", 1.0))),
            },
        )

        vae_decode = graph.add_node(
            "VAEDecode",
            {
                "samples": [ksampler, 0],
                "vae": [ckpt, 2],
            },
        )
        save_image = graph.add_node(
            "SaveImage",
            {
                "images": [vae_decode, 0],
                "filename_prefix": str(_coalesce(where, "filename_prefix", "ComfySQL")),
            },
        )

        trace.append(f"Added KSampler ({ksampler}), VAEDecode ({vae_decode}), SaveImage ({save_image})")

        return PlanResult(
            prompt=graph.prompt,
            output_node_id=save_image,
            output_slot=0,
            trace=trace,
        )

    def _build_dynamic(self, output_name: str, table_name: str, where: dict[str, Any]) -> PlanResult:
        node_class = self._resolve_node_class(table_name)
        graph = PromptGraph()
        trace: list[str] = []

        builder = _DynamicBuilder(self.schema, graph, where, trace)
        root_ref = builder.instantiate_node(node_class, purpose="root")

        final_ref = builder.materialize_output(root_ref, output_name)
        trace.append(f"Materialized SELECT {output_name} from node {final_ref[0]}")

        return PlanResult(
            prompt=graph.prompt,
            output_node_id=final_ref[0],
            output_slot=final_ref[1],
            trace=trace,
        )

    def _resolve_node_class(self, table_name: str) -> str:
        if table_name in self.schema.nodes:
            return table_name

        lower = table_name.lower()
        for class_type in self.schema.nodes:
            if class_type.lower() == lower:
                return class_type

        raise PlanningError(f"Unknown table/template/node '{table_name}'")


class _DynamicBuilder:
    def __init__(
        self,
        schema: SchemaRegistry,
        graph: PromptGraph,
        where: dict[str, Any],
        trace: list[str],
    ):
        self.schema = schema
        self.graph = graph
        self.where = where
        self.trace = trace
        self.provider_cache: dict[tuple[str, str], NodeOutputRef] = {}
        self._instantiation_stack: list[str] = []

    def instantiate_node(self, class_type: str, purpose: str) -> NodeOutputRef:
        if class_type not in self.schema.nodes:
            raise PlanningError(f"Unknown node class '{class_type}'")

        if class_type in self._instantiation_stack:
            raise PlanningError(f"Detected recursive dependency while building '{class_type}'")

        self._instantiation_stack.append(class_type)
        try:
            spec = self.schema.nodes[class_type]
            inputs: dict[str, Any] = {}

            for inp in spec.inputs:
                user_value = self._lookup_user_value(class_type, inp, purpose)

                if is_connection_type(inp.type_name):
                    if user_value is not None:
                        raise PlanningError(
                            f"Direct literal override for connection input '{inp.name}' is not supported yet"
                        )
                    if inp.required:
                        provider_ref = self._provide_type(inp.type_name, inp.name)
                        inputs[inp.name] = [provider_ref[0], provider_ref[1]]
                    continue

                if user_value is not None:
                    inputs[inp.name] = self._cast_primitive(inp, user_value)
                    continue

                # Friendly aliases for common prompt terms.
                if inp.name == "text":
                    if purpose == "negative" and "negative_prompt" in self.where:
                        inputs[inp.name] = str(self.where["negative_prompt"])
                        continue
                    if "prompt" in self.where:
                        inputs[inp.name] = str(self.where["prompt"])
                        continue

                if inp.default is not None:
                    inputs[inp.name] = inp.default
                    continue

                if inp.type_name == "COMBO" and inp.choices:
                    inputs[inp.name] = inp.choices[0]
                    continue

                if inp.required:
                    raise PlanningError(
                        f"Missing required value for {class_type}.{inp.name} ({inp.type_name})"
                    )

            node_id = self.graph.add_node(class_type, inputs)
            self.trace.append(f"Added node {class_type} ({node_id})")

            return node_id, 0
        finally:
            self._instantiation_stack.pop()

    def materialize_output(self, root_ref: NodeOutputRef, output_name: str) -> NodeOutputRef:
        output_name = output_name.lower()
        root_node = self.graph.prompt[root_ref[0]]
        root_type = root_node["class_type"]
        root_spec = self.schema.nodes.get(root_type)

        if root_spec is None:
            return root_ref

        root_output_types = root_spec.output_types
        if not root_output_types:
            raise PlanningError(f"Node {root_type} has no outputs")

        if output_name == "image":
            # Common adaptation: LATENT -> IMAGE via VAEDecode, then SaveImage.
            if "LATENT" in root_output_types:
                latent_slot = root_output_types.index("LATENT")
                vae_provider = self._provide_type("VAE", "vae")
                decode = self.graph.add_node(
                    "VAEDecode",
                    {
                        "samples": [root_ref[0], latent_slot],
                        "vae": [vae_provider[0], vae_provider[1]],
                    },
                )
                save = self.graph.add_node(
                    "SaveImage",
                    {
                        "images": [decode, 0],
                        "filename_prefix": str(self.where.get("filename_prefix", "ComfySQL")),
                    },
                )
                self.trace.append(f"Added VAEDecode ({decode}) + SaveImage ({save}) for image output")
                return save, 0

            # If root already outputs IMAGE, append SaveImage sink for persistence.
            if "IMAGE" in root_output_types:
                if root_type == "SaveImage":
                    return root_ref
                img_slot = root_output_types.index("IMAGE")
                save = self.graph.add_node(
                    "SaveImage",
                    {
                        "images": [root_ref[0], img_slot],
                        "filename_prefix": str(self.where.get("filename_prefix", "ComfySQL")),
                    },
                )
                self.trace.append(f"Added SaveImage ({save})")
                return save, 0

        if output_name in ("latent", "conditioning", "model", "clip", "vae", "video"):
            wanted_type = output_name.upper()
            if wanted_type in root_output_types:
                slot = root_output_types.index(wanted_type)
                return root_ref[0], slot

        # Fallback: return root node first output.
        return root_ref

    def _provide_type(self, type_name: str, consumer_input: str) -> NodeOutputRef:
        purpose = consumer_input.lower()

        cache_key = (type_name, purpose)
        if cache_key in self.provider_cache:
            return self.provider_cache[cache_key]

        # Reuse one shared checkpoint node for MODEL/CLIP/VAE.
        if type_name in ("MODEL", "CLIP", "VAE"):
            checkpoint_key = ("CHECKPOINT", "shared")
            if checkpoint_key in self.provider_cache:
                checkpoint_ref = self.provider_cache[checkpoint_key]
                output_slot = {"MODEL": 0, "CLIP": 1, "VAE": 2}[type_name]
                ref = (checkpoint_ref[0], output_slot)
                self.provider_cache[cache_key] = ref
                return ref

        if type_name == "LATENT" and self.where.get("input_image"):
            img_ref = self._provide_type("IMAGE", "input_image")
            vae_ref = self._provide_type("VAE", "vae")
            node_id = self.graph.add_node(
                "VAEEncode",
                {
                    "pixels": [img_ref[0], img_ref[1]],
                    "vae": [vae_ref[0], vae_ref[1]],
                },
            )
            ref = (node_id, 0)
            self.provider_cache[cache_key] = ref
            self.trace.append(f"Auto-wired LATENT via LoadImage->VAEEncode ({node_id})")
            return ref

        preferred = DEFAULT_TYPE_PROVIDERS.get(type_name)
        if preferred and preferred[0] in self.schema.nodes:
            class_type, default_slot = preferred
            instantiate_purpose = purpose
            if type_name == "CONDITIONING" and purpose.startswith("negative"):
                instantiate_purpose = "negative"
            ref = self.instantiate_node(class_type, purpose=instantiate_purpose)

            # Respect known default slot when provider has multiple outputs.
            ref = (ref[0], default_slot)
            self.provider_cache[cache_key] = ref
            if class_type == "CheckpointLoaderSimple":
                self.provider_cache[("CHECKPOINT", "shared")] = (ref[0], 0)
            return ref

        candidates = self.schema.output_type_index.get(type_name, [])
        candidates = [c for c in candidates if c not in self._instantiation_stack]
        if not candidates:
            raise PlanningError(f"No provider found for required type '{type_name}'")

        class_type = self._pick_best_candidate(candidates)
        ref = self.instantiate_node(class_type, purpose=purpose)

        output_types = self.schema.nodes[class_type].output_types
        slot = output_types.index(type_name) if type_name in output_types else 0
        ref = (ref[0], slot)

        self.provider_cache[cache_key] = ref
        return ref

    def _pick_best_candidate(self, candidates: list[str]) -> str:
        def score(class_type: str) -> tuple[int, int, int]:
            spec = self.schema.nodes[class_type]
            required_connection_inputs = 0
            required_missing_defaults = 0
            for inp in spec.inputs:
                if not inp.required:
                    continue
                if is_connection_type(inp.type_name):
                    required_connection_inputs += 1
                elif inp.default is None and inp.type_name != "COMBO":
                    required_missing_defaults += 1
            output_penalty = 1 if spec.output_node else 0
            return (required_connection_inputs, required_missing_defaults, output_penalty)

        ranked = sorted(candidates, key=score)
        return ranked[0]

    def _cast_primitive(self, inp: InputSpec, value: Any) -> Any:
        if inp.type_name == "INT":
            return int(value)
        if inp.type_name in ("FLOAT", "NUMBER"):
            return float(value)
        if inp.type_name == "BOOLEAN":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() == "true"
            return bool(value)
        if inp.type_name == "STRING":
            return str(value)
        if inp.type_name == "COMBO":
            if inp.choices and value not in inp.choices:
                raise PlanningError(
                    f"Invalid value '{value}' for {inp.name}. Allowed values include: {inp.choices[:10]}"
                )
            return value
        return value

    def _lookup_user_value(self, class_type: str, inp: InputSpec, purpose: str) -> Any:
        key = inp.name.lower()
        if key in self.where:
            return self.where[key]

        # Cross-node aliases so SQL can stay semantic.
        if key == "ckpt_name" and "checkpoint" in self.where:
            return self.where["checkpoint"]
        if key == "sampler_name" and "sampler" in self.where:
            return self.where["sampler"]
        if key == "image" and "input_image" in self.where:
            return self.where["input_image"]
        if key == "text":
            if purpose == "negative" and "negative_prompt" in self.where:
                return self.where["negative_prompt"]
            if "prompt" in self.where:
                return self.where["prompt"]

        # Node-specific aliases.
        if class_type == "CheckpointLoaderSimple" and key == "ckpt_name":
            return self.where.get("checkpoint")

        return None
