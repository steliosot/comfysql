### Examples

1. Text to image + lens_50mm

```sql
SELECT image FROM txt2img_empty_latent 
  PROFILE lens_50mm WHERE 
  prompt='a cinematic portrait of a man' 
  AND seed=100;
```

![ComfyUI_00029_](/Users/stelios/Desktop/ComfyUI_00029_.png)

 `45.84 seconds`

2. Text to image + portrait_85mm

```
SELECT image FROM txt2img_empty_latent 
  PROFILE portrait_85mm WHERE 
  prompt='A natural portrait of a man, realistic skin texture, sharp focus, cinematic lighting, shallow depth of field, soft background blur, professional photography, 85mm lens' 
  AND seed=100
  AND steps = 25;
```

![ComfyUI_00030_](/Users/stelios/Desktop/ComfyUI_00030_.png)

`23.50 seconds`

3. Text to image + reel_9x16

```sql
SELECT image 
FROM txt2img_empty_latent 
PROFILE reel_9x16 
WHERE prompt = 'A vertical cinematic shot of a confident man standing in a modern city, full body centered, natural pose, looking at camera, soft cinematic lighting, shallow depth of field, urban background, realistic skin texture, shot on DSLR, 9:16 composition, subject framed vertically, social media reel style'
  AND seed = 42;
```

![ComfyUI_00031_](/Users/stelios/Desktop/ComfyUI_00031_.png)

`46.50 seconds`

4. Text to image + wide

```
SELECT image FROM txt2img_empty_latent PROFILE story_9x16 
WHERE prompt = 'A cinematic wide shot of a cowboy standing in a vast desert landscape, dramatic sunset lighting, long shadows, dusty atmosphere, mountains in the background, western movie scene, ultra realistic, film still, 21:9 aspect ratio, epic composition'
  AND seed = 77;
```

![ComfyUI_00032_](/Users/stelios/Desktop/ComfyUI_00032_.png)

`48.64 seconds`

5. Image to Image

```
SELECT image FROM img2img_reference PROFILE lens_50mm WHERE prompt=A cinematic wide shot of a cowboy standing in a vast desert landscape, dramatic sunset lighting, long shadows, dusty atmosphere, mountains in the background, western movie scene, ultra realistic, film still, 21:9 aspect ratio, epic composition`
AND image='man-standing.jpg';
```

**Photo of man**

![man-standing](/Users/stelios/Downloads/ComfyUI-custom/input/assets/man-standing.jpg)

![img_00139_](/Users/stelios/Desktop/img_00139_.png)

`87.06 seconds`

6. Image to image+mediumshot_natural

```
SELECT image FROM img2img_reference PROFILE mediumshot_natural WHERE prompt=A cinematic wide shot of a cowboy standing in a vast desert landscape, dramatic sunset lighting, long shadows, dusty atmosphere, mountains in the background, western movie scene, ultra realistic, film still, 21:9 aspect ratio, epic composition`
AND image='man-standing.jpg';
```

![img_00140_](/Users/stelios/Desktop/img_00140_.png)

`45.11 seconds`

7. img2img_2_inputs+dramatic_low_angle

```
SELECT image 
FROM img2img_2_inputs 
PROFILE dramatic_low_angle 
WHERE  prompt = 'A confident man standing in a modern city, captured from a cinematic low-angle perspective. He wears an Apple Watch on his left wrist, naturally positioned and clearly visible, in a relaxed and confident pose. The watch must match the reference image as closely as possible — identical design, shape, materials, colors, and fine details. Ensure the watch face is clearly visible and the numbers are displayed correctly and sharply, exactly as in the reference, without distortion or alteration. The lighting is dramatic and cinematic, with soft shadows across a detailed urban background. Ultra-realistic skin texture, sharp focus, shallow depth of field, and a high-end commercial photography style, resembling a premium advertisement. The watch must preserve the exact visual appearance of the reference image, including the screen layout and numbers, which must be clearly readable, correctly aligned, and not warped or modified. Maintain accurate proportions, perspective, and realistic integration on the wrist.'
  AND 198.image = 'man-standing.jpg'
  AND 213.image = 'applewatch.jpg';
```

<img src="/Users/stelios/Desktop/applewatch.jpg" alt="applewatch" style="zoom:25%;" />![img_00146_](/Users/stelios/Desktop/img_00146_.png)

`45 seconds`

8. Controlnet + goldenhour_backlight

```
SELECT image FROM img2img_controlnet PROFILE goldenhour_backlight 
WHERE prompt='cinematic shot of a post-apocalyptic world, ruined city, collapsed buildings, sand-covered streets, mad max aesthetic, dramatic sky, dust and smoke, golden hour lighting, volumetric fog, ultra realistic, high detail, epic composition, film still, anamorphic lens';
```

![bbk-euston](/Users/stelios/Downloads/bbk-euston.jpg)



![image-20260410195416239](/Users/stelios/Library/Application Support/typora-user-images/image-20260410195416239.png)

`90 seconds`