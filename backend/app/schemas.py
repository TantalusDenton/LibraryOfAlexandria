from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PrintSettings(BaseModel):
    width: float = Field(default=6, ge=4, le=8.5)
    height: float = Field(default=9, ge=6, le=11.69)
    bleed: bool = False
    paper: Literal["white", "cream", "color"] = "white"
    margin: float = Field(default=0.5, ge=0.375, le=1.5)
    minimum_dpi: int = Field(default=300, ge=300, le=600)


class ProjectInput(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    author: str = Field(min_length=1, max_length=240)
    original_language: str = "English"
    output_language: str = "English"
    book_type: Literal["illustrated", "graphic"] = "illustrated"
    pages_per_chapter: int = Field(default=3, ge=1, le=5)
    style: str = "Dark Gothic Medieval Epic"
    art_description: str = ""
    audience: str = "Adults"
    tone: str = "Faithful, cinematic adaptation"
    edition: str = "Unspecified"
    rights_confirmed: bool = False
    rights_declaration: str = Field(min_length=8, max_length=3000)
    budget_usd: float = Field(default=25, gt=0, le=10000)
    text_model: str = ""
    image_model: str = ""
    quality: Literal["low", "medium", "high"] = "low"
    print: PrintSettings = Field(default_factory=PrintSettings)

    @model_validator(mode="after")
    def confirm_rights(self):
        if not self.rights_confirmed:
            raise ValueError("Confirm publishing rights in your target markets")
        return self


class Passage(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class Event(BaseModel):
    id: str
    description: str
    essential: bool = True


class Summary(BaseModel):
    summary: str
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    dialogue: list[str] = Field(default_factory=list)
    developments: list[str] = Field(default_factory=list)


class StoryAnalysis(BaseModel):
    synopsis: str
    themes: list[str]
    continuity: list[str]
    adaptation_strategy: str
    ending: str


class CharacterDesign(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str
    age: str = "Unspecified"
    appearance: str
    hair: str = "Unspecified"
    eyes: str = "Unspecified"
    face: str = "Unspecified"
    body: str = "Unspecified"
    personality: str = ""
    clothing: str = ""
    accessories: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    arc: str = ""
    timeline: list[str] = Field(default_factory=list)
    visual_description: str
    consistency: str
    alternate_designs: list[str] = Field(default_factory=list)


class CharacterList(BaseModel):
    characters: list[CharacterDesign]


class PanelScript(BaseModel):
    scene: str
    narration: str = ""
    dialogue: list[str] = Field(default_factory=list)


class Script(BaseModel):
    narration: str
    scene: str
    characters: list[str]
    location: str
    time_of_day: str
    emotional_tone: str
    continuity: list[str]
    image_prompt: str
    source_passages: list[Passage]
    covered_event_ids: list[str]
    panels: list[PanelScript] = Field(default_factory=list, max_length=6)


class EventAssignment(BaseModel):
    event_id: str
    page_index: int


class Plan(BaseModel):
    page_briefs: list[str]
    assignments: list[EventAssignment]
    condensation_notes: str

    @property
    def event_to_page(self):
        return {assignment.event_id: assignment.page_index for assignment in self.assignments}


class VisualQA(BaseModel):
    passed: bool
    identity_issues: list[str]
    continuity_issues: list[str]
    narrative_issues: list[str]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=10, max_length=200)


class LayoutElementInput(BaseModel):
    kind: Literal["narration", "dialogue", "caption", "speech"]
    text: str = Field(max_length=4000)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    font_size: float = Field(default=12, ge=6, le=48)

    @model_validator(mode="after")
    def fits(self):
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("Layout element lies outside page")
        return self
