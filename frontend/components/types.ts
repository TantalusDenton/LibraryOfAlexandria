export interface Config {
  style_reference_keys?: string[];
  original_language: string;
  output_language: string;
  book_type: string;
  pages_per_chapter: number;
  style: string;
  art_description: string;
  audience: string;
  tone: string;
  edition: string;
  text_model: string;
  image_model: string;
  quality: string;
  print: PrintSpec;
}
export interface PrintSpec {
  width: number;
  height: number;
  bleed: boolean;
  paper: string;
  margin: number;
  minimum_dpi: number;
}
export interface Metrics {
  chapters: number;
  chapters_completed: number;
  pages: number;
  pages_generated: number;
  characters: number;
  references_approved: number;
  spent_and_reserved_usd: number;
  estimated_remaining_image_usd: number;
  qa_status: string;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  error?: string;
  created_at: string;
  target_id?: string;
}
export interface Chapter {
  id: string;
  position: number;
  title: string;
  start_offset: number;
  end_offset: number;
}
export interface SummaryData {
  summary: string;
  characters: string[];
  locations: string[];
  events: { id: string; description: string; essential: boolean }[];
  dialogue: string[];
  developments: string[];
}
export interface Summary {
  id: string;
  chapter_id: string;
  data: SummaryData;
  approved: boolean;
  version: number;
}
export interface CharacterData {
  name: string;
  aliases: string[];
  role: string;
  age: string;
  appearance: string;
  hair: string;
  eyes: string;
  face: string;
  body: string;
  personality: string;
  clothing: string;
  accessories: string[];
  relationships: string[];
  arc: string;
  timeline: string[];
  visual_description: string;
  consistency: string;
  alternate_designs: string[];
}
export interface Character {
  id: string;
  name: string;
  data: CharacterData;
  locked: boolean;
  approved_reference_id?: string;
}
export interface Reference {
  id: string;
  character_id: string;
  storage_key: string;
  version: number;
  metadata_json: Record<string, unknown>;
}
export interface Page {
  id: string;
  chapter_id: string;
  position: number;
  layout: string;
  approved: boolean;
  current_artwork_id?: string;
}
export interface ScriptData {
  narration: string;
  scene: string;
  characters: string[];
  location: string;
  time_of_day: string;
  emotional_tone: string;
  continuity: string[];
  image_prompt: string;
  source_passages: { start: number; end: number }[];
  covered_event_ids: string[];
  panels: { scene: string; narration: string; dialogue: string[] }[];
}
export interface Script {
  id: string;
  page_id: string;
  data: ScriptData;
  approved: boolean;
  version: number;
}
export interface Artwork {
  id: string;
  page_id: string;
  storage_key: string;
  version: number;
  metadata_json: Record<string, unknown>;
}
export interface ElementData {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  font_size: number;
}
export interface LayoutElement {
  id?: string;
  page_id?: string;
  kind: string;
  data: ElementData;
}
export interface Cover {
  title?: string;
  subtitle?: string;
  author?: string;
  adaptation_credit?: string;
  series?: string;
  volume?: string;
  publisher?: string;
  back_text?: string;
  artwork_key?: string;
  artwork_approved?: boolean;
}
export interface Export {
  id: string;
  created_at: string;
  interior_key: string;
  cover_key: string;
  zip_key: string;
  manifest: {
    page_count: number;
    spine_inches: number;
    qa: {
      publication_ready: boolean;
      warnings: string[];
      effective_dpi: Record<string, number>;
    };
  };
}
export interface Usage {
  id: string;
  kind: string;
  model: string;
  status: string;
  cost_usd: number;
  image_calls: number;
  input_tokens: number;
  output_tokens: number;
  pricing_basis: string;
}
export interface Project {
  id: string;
  title: string;
  author: string;
  status: string;
  budget_usd: number;
  created_at: string;
  config: Config;
  cover: Cover;
  metrics: Metrics;
}
export interface Book extends Project {
  sources: { id: string; source_url?: string; char_count: number }[];
  chapters: Chapter[];
  summaries: Summary[];
  characters: Character[];
  references: Reference[];
  pages: Page[];
  scripts: Script[];
  artworks: Artwork[];
  elements: LayoutElement[];
  jobs: Job[];
  exports: Export[];
  usage: Usage[];
  analysis: { stage: string; data: Record<string, unknown> }[];
}
export interface SystemSettings {
  ai_mode: string;
  text_model: string;
  image_model: string;
  economy_image_model: string;
  pricing_confirmed: boolean;
  api_key_configured: boolean;
  preview_image_ceiling: number;
  final_image_ceiling: number;
  storage: string;
  queue: string;
}
