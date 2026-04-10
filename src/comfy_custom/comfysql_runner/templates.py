from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TemplateColumn:
    name: str
    type_name: str
    required: bool
    default: Any = None
    description: str = ""


@dataclass
class TemplateSpec:
    name: str
    description: str
    output_types: list[str]
    columns: list[TemplateColumn]


IMG2IMG_TEMPLATE = TemplateSpec(
    name="img2img_process",
    description="Standard text-to-image or image-to-image flow with optional input image.",
    output_types=["IMAGE"],
    columns=[
        TemplateColumn("checkpoint", "STRING", True, None, "Checkpoint filename/path."),
        TemplateColumn("prompt", "STRING", True, "", "Positive prompt."),
        TemplateColumn("negative_prompt", "STRING", False, "", "Negative prompt."),
        TemplateColumn("input_image", "STRING", False, None, "Input image filename for img2img."),
        TemplateColumn("width", "INT", False, 1024, "Used when input_image is not set."),
        TemplateColumn("height", "INT", False, 1024, "Used when input_image is not set."),
        TemplateColumn("batch_size", "INT", False, 1, "Used when input_image is not set."),
        TemplateColumn("seed", "INT", False, 0, "Sampling seed."),
        TemplateColumn("steps", "INT", False, 20, "Sampling steps."),
        TemplateColumn("cfg", "FLOAT", False, 8.0, "Classifier-free guidance."),
        TemplateColumn("sampler", "STRING", False, "euler", "Sampler algorithm."),
        TemplateColumn("scheduler", "STRING", False, "normal", "Scheduler."),
        TemplateColumn("denoise", "FLOAT", False, 1.0, "Denoise strength."),
        TemplateColumn("filename_prefix", "STRING", False, "ComfySQL", "Output filename prefix."),
    ],
)


# Keep template definitions available in source, but start with no registered
# built-in templates so users begin from a clean SQL state.
TEMPLATES: dict[str, TemplateSpec] = {}


def get_template(name: str) -> TemplateSpec | None:
    return TEMPLATES.get(name.lower())


def list_templates() -> list[TemplateSpec]:
    return [TEMPLATES[key] for key in sorted(TEMPLATES.keys())]
