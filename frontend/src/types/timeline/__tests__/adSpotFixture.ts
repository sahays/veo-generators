import type { FilmstripSpec, SceneAnalysisRecord, TimelineDoc } from '@/types/insights'

/**
 * Development and test fixture: a 45-second tea commercial ("Kadak Chai —
 * Monsoon"). It follows the timeline.json contract exactly: times are float
 * seconds within [0, duration], lists are sorted by start, ids are 1-based in
 * start order, entities are ordered by descending screen time and
 * `screen_time_sec` is the summed length of the appearances.
 *
 * Used by the vitest suites and by the e2e stub server (`frontend/e2e/stub`).
 * Keep this file free of runtime imports so Node can load it directly.
 */
export const AD_SPOT_ID = 'sa-fixture-ad-spot'

export const AD_SPOT_FILMSTRIP: FilmstripSpec = {
  tile_width: 160,
  tile_height: 90,
  columns: 10,
  rows: 5,
  interval_sec: 1,
  count: 45,
}

export const AD_SPOT_TIMELINE: TimelineDoc = {
  schema_version: 'video-timeline-v1',
  duration_sec: 45,
  content_title: 'Kadak Chai — Monsoon',
  summary:
    'A 45-second tea commercial set on a rainy Mumbai evening. Asha comes home drenched, puts the kettle on and reaches for a pack of Kadak Chai. Her neighbour Mr. Rao turns up at the door with a broken umbrella, and the two end up sharing tea and a joke on the balcony. The spot closes on a product hero shot and the line "Baarish ho ya na ho, Kadak ho."',
  cuts: [3.2, 7.5, 12, 17.4, 22.8, 28, 33.5, 39],
  segments: [
    { id: 'seg-1', start_sec: 0, end_sec: 3.2, title: 'Rain on the window', synopsis: 'Close-up of rain streaking down a window as thunder rolls over the city.', location: 'Apartment window' },
    { id: 'seg-2', start_sec: 3.2, end_sec: 7.5, title: 'Asha comes home soaked', synopsis: 'Asha pushes the door open, drenched, and drops her bag with a sigh.', location: 'Apartment hallway' },
    { id: 'seg-3', start_sec: 7.5, end_sec: 12, title: 'The kettle goes on', synopsis: 'She fills the kettle and lights the stove while towelling her hair.', location: 'Kitchen' },
    { id: 'seg-4', start_sec: 12, end_sec: 17.4, title: 'Kadak Chai pack reveal', synopsis: 'Her hand reaches past other jars to the bright orange Kadak Chai pack.', location: 'Kitchen' },
    { id: 'seg-5', start_sec: 17.4, end_sec: 22.8, title: 'Pour and first sip', synopsis: 'Tea is poured from a height into a steel tumbler; Asha takes the first sip and closes her eyes.', location: 'Kitchen' },
    { id: 'seg-6', start_sec: 22.8, end_sec: 28, title: 'Neighbour at the door', synopsis: 'The doorbell rings. Mr. Rao stands outside holding an umbrella turned inside out.', location: 'Apartment hallway' },
    { id: 'seg-7', start_sec: 28, end_sec: 33.5, title: 'Shared laughter on the balcony', synopsis: 'The two share tea on the balcony and laugh as the rain eases.', location: 'Balcony' },
    { id: 'seg-8', start_sec: 33.5, end_sec: 39, title: 'Product hero shot', synopsis: 'Slow push-in on the Kadak Chai pack beside two steaming tumblers.', location: 'Balcony' },
    { id: 'seg-9', start_sec: 39, end_sec: 45, title: 'Tagline and call to action', synopsis: 'Logo, tagline and an offer card: scan to get the monsoon pack.', location: 'End card' },
  ],
  cues: [
    { id: 'cue-1', start_sec: 0, end_sec: 3.2, text: 'Heavy rain and distant thunder', kind: 'sfx', sentiment: 'neutral' },
    { id: 'cue-2', start_sec: 1.1, end_sec: 3, speaker: 'Narrator', text: 'Some evenings arrive all at once.', kind: 'narration', sentiment: 'neutral' },
    { id: 'cue-3', start_sec: 3.4, end_sec: 4.6, text: 'Door creaks open, bag drops', kind: 'sfx', sentiment: 'neutral' },
    { id: 'cue-4', start_sec: 4.8, end_sec: 7.2, speaker: 'Asha', text: 'Uff. Not one auto in this whole city.', kind: 'dialogue', sentiment: 'negative' },
    { id: 'cue-5', start_sec: 7.5, end_sec: 12, text: 'Soft tabla and guitar theme begins', kind: 'music', sentiment: 'positive' },
    { id: 'cue-6', start_sec: 8.2, end_sec: 10.4, speaker: 'Narrator', text: 'But every monsoon has its own small ritual.', kind: 'narration', sentiment: 'positive' },
    { id: 'cue-7', start_sec: 12.3, end_sec: 14.9, speaker: 'Narrator', text: 'Kadak Chai. Assam leaf, crushed ginger, a hint of cardamom.', kind: 'narration', sentiment: 'positive' },
    { id: 'cue-8', start_sec: 15.2, end_sec: 17.2, text: 'Pack tears open, leaves hit boiling water', kind: 'sfx', sentiment: 'neutral' },
    { id: 'cue-9', start_sec: 17.4, end_sec: 19.6, text: 'Tea pouring into a steel tumbler', kind: 'sfx', sentiment: 'positive' },
    { id: 'cue-10', start_sec: 20.1, end_sec: 22.4, speaker: 'Asha', text: 'Mmm. Now it feels like home.', kind: 'dialogue', sentiment: 'positive' },
    { id: 'cue-11', start_sec: 22.8, end_sec: 23.6, text: 'Doorbell', kind: 'sfx', sentiment: 'neutral' },
    { id: 'cue-12', start_sec: 24, end_sec: 26.3, speaker: 'Mr. Rao', text: 'Beta, my umbrella has resigned. Is that ginger I smell?', kind: 'dialogue', sentiment: 'positive' },
    { id: 'cue-13', start_sec: 26.5, end_sec: 27.8, speaker: 'Asha', text: 'Come in, Rao uncle. There is plenty.', kind: 'dialogue', sentiment: 'positive' },
    { id: 'cue-14', start_sec: 28, end_sec: 39, text: 'Theme swells with full band', kind: 'music', sentiment: 'positive' },
    { id: 'cue-15', start_sec: 29.2, end_sec: 31.4, speaker: 'Mr. Rao', text: 'At my age, the tea should be stronger than the knees.', kind: 'dialogue', sentiment: 'positive' },
    { id: 'cue-16', start_sec: 31.5, end_sec: 33.3, text: 'Both laugh', kind: 'sfx', sentiment: 'positive' },
    { id: 'cue-17', start_sec: 34.2, end_sec: 37.6, speaker: 'Narrator', text: 'Kadak Chai. Made strong, for the days that need it.', kind: 'narration', sentiment: 'positive' },
    { id: 'cue-18', start_sec: 39, end_sec: 40.2, text: 'Brief pause before the tagline', kind: 'silence', sentiment: 'neutral' },
    { id: 'cue-19', start_sec: 40.2, end_sec: 42.8, speaker: 'Narrator', text: 'Baarish ho ya na ho, Kadak ho.', kind: 'narration', sentiment: 'positive' },
    { id: 'cue-20', start_sec: 43, end_sec: 45, speaker: 'Narrator', text: 'Scan now for the monsoon pack. Offer ends 31 August.', kind: 'narration', sentiment: 'neutral' },
  ],
  entities: [
    { id: 'ent-1', name: 'Asha', kind: 'character', description: 'Woman in her late twenties, office wear, wet hair.', appearances: [{ start_sec: 3.2, end_sec: 12 }, { start_sec: 17.4, end_sec: 33.5 }], screen_time_sec: 24.9 },
    { id: 'ent-2', name: 'Kadak Chai pack', kind: 'object', description: 'Bright orange 250 g pouch with a steaming-cup logo.', appearances: [{ start_sec: 12, end_sec: 17.4 }, { start_sec: 20.5, end_sec: 22.8 }, { start_sec: 33.5, end_sec: 45 }], screen_time_sec: 19.2 },
    { id: 'ent-3', name: 'Steel tumblers', kind: 'object', description: 'Two traditional steel tumblers with saucers.', appearances: [{ start_sec: 17.4, end_sec: 22.8 }, { start_sec: 28, end_sec: 39 }], screen_time_sec: 16.4 },
    { id: 'ent-4', name: 'Kitchen', kind: 'location', description: 'Small tiled kitchen with a gas stove and open shelves.', appearances: [{ start_sec: 7.5, end_sec: 22.8 }], screen_time_sec: 15.3 },
    { id: 'ent-5', name: 'Balcony', kind: 'location', description: 'Narrow balcony with potted tulsi, overlooking a wet street.', appearances: [{ start_sec: 28, end_sec: 39 }], screen_time_sec: 11 },
    { id: 'ent-6', name: 'Mr. Rao', kind: 'character', description: 'Neighbour in his sixties, kurta and a broken umbrella.', appearances: [{ start_sec: 23.4, end_sec: 33.5 }], screen_time_sec: 10.1 },
    { id: 'ent-7', name: 'Kettle', kind: 'object', description: 'Dented aluminium kettle on the stove.', appearances: [{ start_sec: 7.9, end_sec: 12 }, { start_sec: 15.2, end_sec: 19.6 }], screen_time_sec: 8.5 },
    { id: 'ent-8', name: 'Broken umbrella', kind: 'object', description: 'Black umbrella turned inside out.', appearances: [{ start_sec: 23.4, end_sec: 28 }], screen_time_sec: 4.6 },
    { id: 'ent-9', name: 'Offer QR code', kind: 'object', description: 'QR code on the end card.', appearances: [{ start_sec: 42.8, end_sec: 45 }], screen_time_sec: 2.2 },
  ],
  events: [
    { id: 'evt-1', start_sec: 0, end_sec: 3.2, tag: 'exposition', description: 'Establishing the storm.', intensity: 0.4 },
    { id: 'evt-2', start_sec: 3.2, end_sec: 7.5, tag: 'emotional', description: 'A tired, frustrated arrival.', intensity: 0.5 },
    { id: 'evt-3', start_sec: 7.5, end_sec: 12, tag: 'music', description: 'Theme music enters as the mood turns.', intensity: 0.5 },
    { id: 'evt-4', start_sec: 12, end_sec: 17.4, tag: 'product_showcase', description: 'First clear view of the pack and ingredients.', intensity: 0.8 },
    { id: 'evt-5', start_sec: 17.4, end_sec: 22.8, tag: 'emotional', description: 'The pour and first sip: comfort lands.', intensity: 0.85 },
    { id: 'evt-6', start_sec: 22.8, end_sec: 24, tag: 'transition', description: 'Doorbell interrupts the quiet.', intensity: 0.45 },
    { id: 'evt-7', start_sec: 24, end_sec: 33.5, tag: 'comedy', description: 'Banter with the neighbour builds to the knees joke.', intensity: 0.75 },
    { id: 'evt-8', start_sec: 33.5, end_sec: 39, tag: 'product_showcase', description: 'Hero shot of the pack with two tumblers.', intensity: 0.9 },
    { id: 'evt-9', start_sec: 39, end_sec: 45, tag: 'call_to_action', description: 'Tagline, logo and scan-to-buy offer.', intensity: 0.7 },
  ],
  emotions: [
    { id: 'emo-1', start_sec: 0, end_sec: 3.2, emotion: 'calm', intensity: 0.35 },
    { id: 'emo-2', start_sec: 3.2, end_sec: 7.5, emotion: 'sadness', intensity: 0.5 },
    { id: 'emo-3', start_sec: 7.5, end_sec: 12, emotion: 'calm', intensity: 0.55 },
    { id: 'emo-4', start_sec: 12, end_sec: 17.4, emotion: 'surprise', intensity: 0.6 },
    { id: 'emo-5', start_sec: 17.4, end_sec: 22.8, emotion: 'joy', intensity: 0.85 },
    { id: 'emo-6', start_sec: 22.8, end_sec: 24.5, emotion: 'suspense', intensity: 0.4 },
    { id: 'emo-7', start_sec: 24.5, end_sec: 33.5, emotion: 'humor', intensity: 0.8 },
    { id: 'emo-8', start_sec: 28, end_sec: 39, emotion: 'joy', intensity: 0.7 },
    { id: 'emo-9', start_sec: 33.5, end_sec: 39, emotion: 'triumph', intensity: 0.9 },
    { id: 'emo-10', start_sec: 39, end_sec: 45, emotion: 'calm', intensity: 0.5 },
  ],
  key_moments: [
    { id: 'km-1', start_sec: 0.4, type: 'hook', label: 'Rain-streaked window opens the spot' },
    { id: 'km-2', start_sec: 13.1, type: 'product_reveal', label: 'Hand lands on the Kadak Chai pack' },
    { id: 'km-3', start_sec: 20.6, type: 'emotional_peak', label: 'First sip, eyes closed' },
    { id: 'km-4', start_sec: 24.2, type: 'reveal', label: 'Mr. Rao and the inside-out umbrella' },
    { id: 'km-5', start_sec: 30.9, type: 'punchline', label: '"Stronger than the knees"' },
    { id: 'km-6', start_sec: 31.6, type: 'emotional_peak', label: 'Shared laughter' },
    { id: 'km-7', start_sec: 35, type: 'product_reveal', label: 'Hero shot with two tumblers' },
    { id: 'km-8', start_sec: 40.4, type: 'call_to_action', label: 'Tagline: "Baarish ho ya na ho, Kadak ho."' },
    { id: 'km-9', start_sec: 43.2, type: 'call_to_action', label: 'Scan for the monsoon pack' },
  ],
  narrative_beats: [
    { id: 'nb-1', start_sec: 0, end_sec: 7.5, beat: 'setup', label: 'A rough, rainy evening' },
    { id: 'nb-2', start_sec: 7.5, end_sec: 12, beat: 'inciting_incident', label: 'She turns to her ritual' },
    { id: 'nb-3', start_sec: 12, end_sec: 22.8, beat: 'rising_action', label: 'The tea is made and tasted' },
    { id: 'nb-4', start_sec: 22.8, end_sec: 33.5, beat: 'climax', label: 'An uninvited guest becomes company' },
    { id: 'nb-5', start_sec: 33.5, end_sec: 39, beat: 'falling_action', label: 'The product takes the frame' },
    { id: 'nb-6', start_sec: 39, end_sec: 45, beat: 'resolution', label: 'Tagline and offer' },
  ],
}

const TIMELINE_COUNTS: Record<string, number> = {
  segments: AD_SPOT_TIMELINE.segments.length,
  cues: AD_SPOT_TIMELINE.cues.length,
  entities: AD_SPOT_TIMELINE.entities.length,
  events: AD_SPOT_TIMELINE.events.length,
  emotions: AD_SPOT_TIMELINE.emotions.length,
  key_moments: AD_SPOT_TIMELINE.key_moments.length,
  narrative_beats: AD_SPOT_TIMELINE.narrative_beats.length,
}

/** Completed record matching `AD_SPOT_TIMELINE`. */
export const AD_SPOT_RECORD: SceneAnalysisRecord = {
  id: AD_SPOT_ID,
  source_type: 'upload',
  source_id: 'upl-fixture-ad-spot',
  video_gcs_uri: 'gs://fixture-bucket/uploads/kadak-chai-monsoon-45s.mp4',
  video_filename: 'kadak-chai-monsoon-45s.mp4',
  display_name: 'Kadak Chai — Monsoon (45s)',
  mime_type: 'video/mp4',
  focus: 'Product shots and brand mentions',
  model_id: 'gemini-3.8-flash',
  region: 'global',
  status: 'completed',
  stage: 'completed',
  stage_detail: '',
  progress_pct: 100,
  error_message: null,
  duration_sec: AD_SPOT_TIMELINE.duration_sec,
  window_count: 1,
  summary: AD_SPOT_TIMELINE.summary,
  content_title: AD_SPOT_TIMELINE.content_title,
  counts: TIMELINE_COUNTS,
  filmstrip: AD_SPOT_FILMSTRIP,
  schema_version: AD_SPOT_TIMELINE.schema_version,
  usage: { input_tokens: 14820, output_tokens: 3160, model_name: 'gemini-3.8-flash', cost_usd: 0.0123 },
  video_signed_url: '/media/ad-spot.mp4',
  archived: false,
  createdAt: '2026-11-12T09:30:00Z',
  completedAt: '2026-11-12T09:31:12Z',
}
