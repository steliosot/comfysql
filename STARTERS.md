## Starters Tutorial

Primary CLI is `comfysql`. `comfy-agent` is kept as a compatibility alias.

### Part 1: Fundamentals

Connect to the ComfySQL server:

```bash
comfysql sql remote
```

Before running generation queries, sync schema/model inventory once:

```bash
comfysql sync remote
```

If you want the outputs to be downloaded locally:

```bash
comfysql sql remote --download-output --download-dir ./output/test_folder
```

> `test_folder` is where the generated assets will be stored.

To exit the SQL terminal:

```bash
.exit
```

For one-line SQL, semicolon is optional. For multiline SQL, always end the statement with `;`.

Your input folder for local assets is:

```bash
input/assets
```

After placing an image locally, you must explicitly copy it to the server input. Run this in the terminal (not the SQL terminal):

```bash
comfysql copy-assets remote input/assets/bets.png
```

Workflows already exist in this setup. Use this command to list them (first connect using `comfysql sql remote`):

```sql
SHOW TABLES workflows;
```

Describe a workflow:

```sql
DESCRIBE WORKFLOW txt2img_empty_latent;
```

You can also run commands directly from the terminal:

```bash
comfysql sql remote --sql "DESCRIBE WORKFLOW txt2img_empty_latent;"
```

### Part 2: Profiles

Profiles are reusable metadata that act as styles on top of queries.

List available profiles:

```sql
SHOW TABLES profiles;
```

Describe a profile:

```sql
DESCRIBE PROFILE hd_720p;
```

Create a new profile:

```sql
CREATE PROFILE starter_portrait_v1 
  WITH width=1024 
  AND height=1024 
  AND lens='50mm (Standard)' 
  AND camera_distance='Medium Close-Up';
```

Reply `y` to:

```
This statement can change state. Continue? [y/N]:
```

This is just a safety confirmation.

### Part 3: Presets

A preset is a saved set of technical parameters for a specific workflow.

List presets:

```sql
SHOW PRESETS;
```

Describe a preset:

```sql
DESCRIBE PRESET default_run FOR img2img_2_inputs;
```

Create a new preset with a specific scheduler and sampler:

```sql
CREATE PRESET txt2img_normal_sched_v1
FOR txt2img_empty_latent
WITH scheduler='normal' AND sampler_name='karras';
```

To create a preset with default values:

```sql
CREATE PRESET my_new_preset
FOR txt2img_empty_latent
AS DEFAULTS;
```

You can remove presets or tables using:

```sql
DROP PRESET my_new_preset FOR txt2img_empty_latent;
```

### Part 4: Running Workflows

Validate a workflow before running it:

```sql
EXPLAIN 
SELECT image 
FROM txt2img_empty_latent 
USING default_run 
PROFILE goldenhour_backlight 
WHERE prompt='cinematic portrait of a person in central London at golden hour' 
AND filename_prefix='txt2img_seed123_1';
```

> `EXPLAIN` compiles and validates the query but does not execute it.
> If you get `validation_failed: ... unknown class_type ...`, refresh and re-import the workflow from your current Comfy instance:
>
> ```bash
> comfysql sync remote
> comfysql sql remote --sql "CREATE TABLE txt2img_empty_latent AS WORKFLOW 'input/workflows/txt2img_empty_latent.json';"
> ```

Run the workflow:

```sql
SELECT image 
FROM txt2img_empty_latent 
USING default_run 
PROFILE goldenhour_backlight 
WHERE prompt='cinematic portrait of a person in central London at golden hour' 
AND seed=123
AND filename_prefix='txt2img_seed123_1';
```

> Always provide a `filename_prefix` so ComfySQL knows what to download.

Outputs will be saved in:

```
./output/
```

Generate a report for the run:

```sql
REPORT
SELECT image
FROM txt2img_empty_latent
USING default_run
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait of a person in central London at golden hour'
AND seed=123
AND filename_prefix='txt2img_seed123_1'
TO './output/report_seed123.md';
```

Open the report in the output folder.

### Part 5: Examining Assets

The `input/assets` folder contains images, videos, and other inputs for ComfyUI.

You can create reusable components in SQL such as `CHARACTERS` and `OBJECTS`.

First copy assets to the server:

```bash
comfysql copy-assets remote --all
```

Create a character called Bets:

```sql
CREATE CHARACTER char_bets WITH image='bets.png';
```

Create another character:

```sql
CREATE CHARACTER char_matt WITH image='matt.png';
```

> Both images must exist in `input/assets`.

Bind a character to a workflow node:

```sql
CREATE SLOT subject FOR img2img_reference AS CHARACTER BINDING input_image;
```

If unsure, inspect the workflow:

```sql
DESCRIBE WORKFLOW img2img_reference;
```

For workflows with numeric node IDs:

```sql
CREATE SLOT subject FOR img2img_2_inputs AS CHARACTER BINDING 198.image;
```

Create a slot for the hat object:

```sql
CREATE SLOT hat FOR img2img_2_inputs AS OBJECT BINDING 213.image;
```

**Run img2img Example**

Using character Matt:

```sql
SELECT image
FROM img2img_reference
USING default_run
CHARACTER char_matt
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait of Matt in central London at sunset'
AND seed=123
AND filename_prefix='img2img_matt_london_123';
```

Using Matt with a hat:

```sql
SELECT image
FROM img2img_2_inputs
USING default_run
CHARACTER char_matt
OBJECT obj_hat
PROFILE goldenhour_backlight
WHERE prompt='cinematic portrait of Matt wearing a summer hat in central London at golden hour'
AND seed=123
AND filename_prefix='img2img2_matt_hat_123';
```

### Part 6: Creating Templates

A template is a reusable workflow definition in ComfySQL. Think of it as a blueprint.

Create a template:

```sql
CREATE TEMPLATE txt2img_starter_template 
AS WORKFLOW 'input/workflows/txt2img_empty_latent.json';
```

Using a template, you can create different presets.

Example: SD1.5 Juggernaut Reborn setup:

```sql
CREATE PRESET juggernaut_reborn_sd15 
FOR txt2img_starter_template 
WITH ckpt_name='sd1.5/juggernaut_reborn.safetensors' 
AND sampler_name='euler' 
AND scheduler='normal' 
AND steps=24 
AND cfg=7;
```

Example: Flux-based setup:

```sql
CREATE PRESET fluxmania_v1 
FOR txt2img_starter_template 
WITH ckpt_name='fluxmania_V' 
AND sampler_name='euler';
```

You can now reuse these presets to run workflows.
