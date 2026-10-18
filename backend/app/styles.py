IVANHOE_STYLE = (
    "Dark gothic medieval atmosphere. Cinematic knight-superhero epic. Historically grounded "
    "12th-century English setting, intricate chainmail and heraldry, monumental Norman castles, violent "
    "storms, dramatic chiaroscuro, realistic faces, painterly textures, cold blue shadows, fiery golden "
    "highlights, bold heroic compositions, mature graphic-novel aesthetic."
)
STYLES = {
    "Dark Gothic Medieval Epic": (
        "cold blue, steel, fiery gold",
        "chiaroscuro",
        "painterly realism",
        IVANHOE_STYLE,
    ),
    "Classical Oil Painting": (
        "umber, ochre, muted gold",
        "soft directional",
        "layered oils",
        "Classical figurative painting",
    ),
    "Realistic Cinematic": (
        "film graded natural colors",
        "cinematic motivated",
        "photorealistic",
        "Wide cinematic staging",
    ),
    "European Graphic Novel": (
        "muted earth colors",
        "dramatic",
        "ink and painted color",
        "Expressive clear-line panels",
    ),
    "Manga": (
        "black and white",
        "high contrast",
        "expressive ink and screentone",
        "Dynamic manga composition",
    ),
    "Watercolor Storybook": (
        "soft pastels",
        "warm diffuse",
        "watercolor paper",
        "Gentle storybook atmosphere",
    ),
    "Fantasy Illustration": (
        "jewel tones",
        "magical volumetric",
        "detailed digital painting",
        "Epic fantasy illustration",
    ),
    "Custom": ("user defined", "user defined", "user defined", "Follow the custom art description"),
}


def style_data(name):
    palette, lighting, technique, atmosphere = STYLES.get(name, STYLES["Custom"])
    return dict(
        palette=palette,
        lighting=lighting,
        rendering_technique=technique,
        atmosphere=atmosphere,
        detail_level="high",
        composition="clear silhouettes, visual hierarchy, print-safe edges",
        negative_constraints="No lettering, captions, speech bubbles, logos, watermarks, modern objects",
        reference_keys=[],
    )


def style_prompt(project):
    import json

    data = style_data(project.config.get("style", "Custom"))
    data["reference_keys"] = project.config.get("style_reference_keys", [])
    return json.dumps(data) + " " + project.config.get("art_description", "")
