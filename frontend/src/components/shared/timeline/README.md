# Timeline kit

Shared building blocks for the two timeline workspaces (Scene Analysis and
Engagement): one media clock, one viewport, aligned lanes, a synced player and
the panels around them.

## Where things live (and why)

The repo's tier checker (`scripts/checkers/arch_tiers.py`) decides the layout:
`hooks/` and `components/shared/` are tier 4 and may not import tier 5, and
`lib/timeline/` would be tier 5. So the pure logic sits in tier 1.

| Path | Tier | Contents |
|---|---|---|
| `src/types/timeline/` | 1 | Pure logic, no React, no DOM: `intervalIndex`, `viewport`, `ticks`, `downsample`, `timeFormat`, `exporters`, `stacking`, `glyphs`, `model`, `series`, `windowing`, `shortcuts`, `textSearch`, `bisect`. Tests and the fixture pair in `__tests__/`. |
| `src/store/timeline/` | 3 | `mediaClock.ts` (`MediaClock`, not React) and `workspaceStore.ts` (per-instance Zustand store). |
| `src/hooks/timeline/` | 4 | `useMediaClock`, `useTimelineViewport`, `timelineContext` (contexts and accessor hooks), `useTimelineGestures`, `useTimeScrub`, `useUrlTimeSync`, `usePlayerShortcuts`, `useWindowedList`, `useElementSize`, `usePrefersReducedMotion`, `useAsyncResource`, `saveFile`. |
| `src/components/shared/timeline/` | 4 | Components. Import them from `@/components/shared/timeline`. `record/` holds the page chrome both features share (header, job progress, export menu, load states). |

Feature-specific pure logic follows the same rule: the Engagement maths
(`StepSeries`, the report model, curve rows, exports) is in
`src/types/engagement/`, and its view state store next to the kit's in
`src/store/timeline/engagementUiStore.ts`.

## Minimal workspace

```tsx
const model = useMemo(() => buildTimelineModel(timeline), [timeline]) // @/types/timeline/model

<TimelineWorkspace duration={model.duration} items={model.itemsById} initial={{ pinnedEntityIds: ['ent-1'] }}>
  <SyncedVideoPlayer src={record.video_signed_url} segments={model.segments}>
    <NowStrip model={model} />
  </SyncedVideoPlayer>

  <TimelineToolbar lanes={[{ id: 'segments', label: 'Segments' }]} />
  <TimelineSurface ariaLabel="Timeline" hoverCard={(t) => <MomentHoverCard model={model} timeSec={t} />}>
    <RulerLane />
    <FilmstripLane filmstrip={filmstrip} />
    <SegmentsLane segments={model.segments} />
    <KeyMomentsLane points={model.moments} />
    <BeatsLane index={model.beats} />
    <EmotionsLane index={model.emotions} />
    <EntityLanes entityById={model.entityById} entityRanges={model.entityRanges} />
    <DensityLane index={speechIndex} />
  </TimelineSurface>
  <Minimap ranges={timeline.segments} />

  <TranscriptPanel cues={model.cues} />
  <EntityBrowser entities={timeline.entities} />
</TimelineWorkspace>
```

`TimelineWorkspace` must wrap everything that uses the kit. Mount one per page.

## Components

| Component | Props | Notes |
|---|---|---|
| `TimelineWorkspace` | `duration`, `items?` (`model.itemsById`, for `?sel=`), `initial?` (`{ pinnedEntityIds?, hiddenLanes?, selection? }`), `children` | Creates the clock, the store and the viewport; wires loop, follow-playhead and URL sync. |
| `SyncedVideoPlayer` | `src`, `segments?`, `title?`, `className?`, `children?` | The `<video>` bound to the clock, transport bar, keyboard shortcuts. |
| `PlayerControls` | `segments?`, `className?` | The transport bar alone. |
| `NowStrip` | `model`, `className?` | Segment, on-screen entities, cue and emotion at the playhead. |
| `TimelineSurface` | `ariaLabel`, `children` (lanes), `hoverCard?: (timeSec) => ReactNode`, `className?` | Owns the scale. Wheel zoom, drag pan, `+` `-` `0` keys, playhead, selection band, crosshair. |
| `TimelineLane` | `id`, `label`, `height`, `labelExtra?`, `className?`, `children` (nodes or `({ scale, width, height }) => ReactNode`) | Generic lane row. **This is where a custom lane plugs in.** |
| `LaneSvg`, `LaneItem` | `label`, `height` / `label`, `selected?`, `tabStop`, `onActivate` | SVG canvas and focusable item for custom SVG lanes. |
| `RulerLane` | `label?` | Ticks, click/drag scrub, Shift+drag range select, arrow keys. |
| `FilmstripLane` | `filmstrip: FilmstripInfo \| null`, `id?`, `label?` | Renders nothing when `null`. |
| `SegmentsLane` | `segments: IntervalIndex<TimelineSegment>`, `id?`, `label?` | |
| `MarkersLane<T>` | `id`, `label`, `kind`, `points: PointIndex<T>`, `describe: (item) => { glyph, description }`, `rows?`, `height?` | Point glyphs with collision stacking. `KeyMomentsLane` (`points`) is the preset. |
| `RangeLane<T>` | `id`, `label`, `kind`, `index: IntervalIndex<T>`, `describe: (item) => { text, description, color, opacity }`, `rows?`, `height?` | Overlapping ranges stack into rows. `EmotionsLane` and `BeatsLane` (`index`) are presets. |
| `EntityLanes` | `entityById`, `entityRanges`, `emptyHint?` | One lane per pinned entity. Lane-visibility id: `ENTITY_LANES_ID`. |
| `DensityLane` | `index: IntervalIndex<TimeRange>`, `id?`, `label?` | Coverage bars. |
| `Minimap` | `ranges?`, `label?`, `className?` | Brush: drag to pan, drag edges to zoom, click track to centre. Put it right under the surface. |
| `TimelineToolbar` | `lanes?: LaneOption[]`, `children?`, `className?` | Range read-out, follow toggle, lane menu, zoom, fit. `LaneToggleMenu` and `ZoomControls` are exported separately. |
| `MomentHoverCard` | `model`, `timeSec` | Default hover-card body. |
| `TranscriptPanel` | `cues: IntervalIndex<TimelineCue>`, `className?` | Give it a bounded height (`flex-1` in a flex column, or a fixed height). |
| `EntityBrowser` | `entities`, `className?` | Same height rule. |
| `PanelSearch`, `Highlighted` | `placeholder` / `text`, `query` | Search box bound to the shared query; match highlighting. |
| `GlyphIcon` | `shape`, `color`, `size?` | The lane glyphs as icons, for lists and legends. |

Layout constants: `TIMELINE_GUTTER_PX`, `LANE_HEIGHT`.

### Record chrome (`record/`)

Both workspaces are record pages around a staged worker job, so the chrome is
shared instead of copied. Scene Analysis and Engagement only supply their own
badges, stages and download items.

| Component | Props | Notes |
|---|---|---|
| `RecordHeader` | `backTo`, `backLabel`, `name`, `defaultName?`, `onRename: (name) => Promise`, `badges?`, `actions?` | Back link, editable name (shows the new name once `onRename` resolves), a row of badges, actions on the right. |
| `RecordStatusPill` | `status` | Status in the app's shared status colours. |
| `DurationPill` | `seconds` | Video length for record cards. |
| `BackLink` | `to`, `label` | |
| `JobProgress` | `ariaLabel`, `stages: JobStage[]`, `activeStage` (the record's `stage`), `failed`, `detail?` (`stage_detail`), `progressPct`, `statusExtra?`, `statusText?`, `children?` | Stage stepper, progress bar and a polite status line. A stage that is not in `stages` (e.g. `''`) means "queued". `data-testid="processing-view"`; each step is `li[data-stage][data-state=done|active|failed|waiting]`. |
| `JobRetryPanel` | `error`, `retryLabel`, `onRetry: () => Promise`, `onRetried`, `hint?` | Error with a Retry button for users who may write. Put it in `JobProgress` when the job failed. |
| `DownloadMenu` | `groups: DownloadGroup[]` (`{ label?, items: { key, label, icon, save }[] }`) | "Export" button with a menu of files generated in the browser. `data-testid="export-menu"`. |
| `LoadingNotice`, `LoadFailure`, `RecordUnavailable` | `label` / `error`, `onRetry` / `error`, `loadingLabel`, `backTo`, `backLabel` | Spinner, error with "Try again", and what a record page shows before it has a record. |

Related helpers: `useAsyncResource(load, key, fallbackError)`
(`@/hooks/timeline/useAsyncResource`) loads a document once per record with
`reload()`; `useCreateRecord({ schema, send, detailPath, ... })`
(`@/hooks/useCreateRecord`) is the Zod-validated submit of a "new job" form;
`defaultPinnedEntityIds(entities)` (`@/types/timeline/model`) picks the
entities pinned when a workspace opens; `activeIndexOf(state)`
(`@/components/ui/chart`) reads the clicked datum of a recharts chart;
`OptionalNameField` (`@/components/shared/WorkPageShell`) is the name input of
the create forms.

## Hooks (`@/hooks/timeline/timelineContext` unless noted)

| Hook | Returns |
|---|---|
| `useTimelineKit()` | `{ clock, store, viewport, duration }`. Stable; reading it never re-renders. |
| `useSeek()` | `(timeSec, { play? }) => void`. Seeks and reveals the time on the timeline. Does not pause. |
| `useSelectItem()` | `(selection) => void`. Selects and seeks to the start. The default click behaviour. |
| `useWorkspace(selector)` | A slice of the workspace store. |
| `useTimelineView()` | The visible range `{ start, end }`. Re-renders on zoom and pan. |
| `useTimeScale()` | The shared scale. Only inside `TimelineSurface`. |
| `useClockTime(clock, stepSec?)` (`useMediaClock`) | Current time rounded down to `stepSec`. For read-outs. |
| `useClockValue(clock, compute, keyOf)` (`useMediaClock`) | A value derived from time; re-renders only when `keyOf(value)` changes. Pass stable callbacks. |
| `useClockState(clock)` (`useMediaClock`) | `{ playing, rate, muted, duration, ready, loop }`. |
| `useTimeScrub()` (`useTimeScrub`) | Pointer handlers that scrub the playhead on press and drag, and select a range on Shift+drag. The ruler uses them; spread them on any element spanning a lane's plot and give it the `NO_PAN_ATTR` attribute (`useTimelineGestures`). Only inside `TimelineSurface`. |

`clock` (`MediaClock`): `seek(t, { play? })`, `play()`, `pause()`, `toggle()`,
`setRate(r)`, `setMuted(b)`, `setLoop(range | null)`, `getTime()`, `getState()`,
`subscribeTime(fn)`, `subscribeState(fn)`, `attach(el)`.

`viewport` (`ViewportApi`): `getView()`, `setView(v)`, `zoomAt(factor, anchorSec)`,
`zoomBy(factor)`, `panBy(sec)`, `fit()`, `showRange(range, padRatio?)`, `reveal(t)`.

## Workspace store (`@/store/timeline/workspaceStore`)

One store per `TimelineWorkspace`, so nothing leaks between records.

State: `selection: TimelineSelection | null`, `pinnedEntityIds: string[]` (at
most `MAX_PINNED_ENTITIES`), `hiddenLanes: string[]`, `search: string`,
`followPlayhead: boolean`, `loopSelection: boolean`.

Actions: `select`, `togglePin`, `toggleLane`, `setSearch`, `setFollowPlayhead`,
`setLoopSelection`. Read with `useWorkspace((s) => s.search)`; write with
`useTimelineKit().store.getState().setSearch('…')`.

`TimelineSelection` is `{ kind, id, label, range }`; `kind: 'range'` with
`id: null` is a free range (Shift+drag on the ruler). Looping uses the
selection's range. `TimelineItemKind` includes `'extremum'` for the peaks,
valleys and drops of an engagement curve: they are not part of a
`TimelineDoc`, so a workspace that has them merges their refs into the `items`
it passes to `TimelineWorkspace` (then `?sel=peak-1` restores like any item).

## Performance rules the kit relies on

- **Time is not React state.** Nothing above a leaf may call `useClockTime`.
  Move things with `clock.subscribeTime` and a transform (see `Playhead`), or
  derive a value with `useClockValue` so the component re-renders only when the
  value changes.
- **Lookups by time go through an index.** Use `IntervalIndex.at / firstAt /
  overlapping` and `PointIndex.between`; do not filter arrays per tick or per
  frame. `buildTimelineModel(doc)` builds every index once.
- **Lanes draw only what is visible.** Query with
  `index.overlapping(scale.view.start, scale.view.end)`.
- **Dense series:** `downsampleForView(points, scale.view, scale.width)` gives
  about one point per pixel and keeps peaks.

## Adding a custom lane (e.g. a Recharts curve)

```tsx
<TimelineLane id="engagement" label="Engagement" height={172}>
  {({ scale, width, height }) =>
    width > 0 && (
      <ChartContainer config={config} className="aspect-auto" style={{ width, height }}>
        <ComposedChart data={rows} margin={{ top: 10, right: 0, bottom: 0, left: 0 }} accessibilityLayer={false}>
          <XAxis type="number" dataKey="t" hide allowDataOverflow domain={[scale.view.start, scale.view.end]} />
          <YAxis hide allowDataOverflow domain={[0, 1]} />
          <Area dataKey="value" type="stepAfter" connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ChartContainer>
    )
  }
</TimelineLane>
```

The plot box is exactly `width` x `height` with no padding, so zero horizontal
margins and an x domain equal to the visible range make the chart line up with
every other lane. Build `rows` with `downsampleForView`. Draw the y axis inside
the plot or in `labelExtra`; never give the chart a left margin. The playhead,
selection band and crosshair are drawn by the surface over all lanes, so a
custom lane does not draw its own.

This recipe is what the Engagement curve lane uses
(`components/pages/engagement/workspace/CurveLane.tsx`) and it is checked in
the browser (`e2e/stub/engagement-workspace.stub.spec.ts`): the chart's SVG
has the left edge and width of every other lane's plot, the dots the chart
draws at known times sit within 0.75 px of where the ruler puts those times
and on the markers of the marker lane, and after a wheel zoom the clock-driven
playhead lands on the dot of the time it was seeked to. What makes it hold:

- **Both horizontal margins are 0 and both axes are `hide`.** A hidden axis
  takes no space; recharts' default margin is 5 px on every side, so the
  margin must be given.
- **`type="number"` with a numeric `domain` and `allowDataOverflow`.** Without
  `allowDataOverflow` recharts widens the domain to the data, which breaks the
  mapping as soon as the view is zoomed; with it the series is clipped to the
  plot instead.
- **Give the container the lane's `width` and `height` in pixels** (through
  `style`; `className="aspect-auto"` switches off the primitive's default
  aspect ratio). `ChartContainer` wraps the chart in a `ResponsiveContainer`,
  which then measures exactly that box. Skip rendering while `width` is 0
  (first layout), otherwise recharts warns about a chart without a size.
- **`isAnimationActive={false}` on every series** of a lane: the rows change
  on every zoom and pan step.
- **`accessibilityLayer={false}`** unless the lane uses the recharts tooltip:
  it would add a tab stop that does nothing. Hover values belong in the
  surface's `hoverCard`, which reads them at the exact time under the cursor.
- **Step series need a closing row.** A value that holds for an interval is
  drawn with `type="stepAfter"`; add one row at `lastTime + interval` so the
  last step is drawn (see `buildCurveRows` in `@/types/engagement/curveRows`).
- **Several series share the rows.** Merge them on time and set `connectNulls`;
  a row carries only the series that have a sample there.
- **Scrubbing.** Spread `useTimeScrub()` on an element covering the plot and
  mark it with `NO_PAN_ATTR`; the chart inside still receives pointer events.

To make a custom SVG lane keyboard accessible, wrap items in `LaneSvg` /
`LaneItem` and give the main shape the class `tl-shape`.

## Keyboard

| Where | Keys |
|---|---|
| Anywhere in the workspace | Space or K play/pause; Left/Right 5 s; J/L 10 s; `[` `]` previous/next segment |
| Ruler (focused) | Left/Right 1 s (Shift 5 s); Home; End |
| A lane (focused item) | Left/Right/Home/End move between items; Enter or Space activates |
| Timeline surface (focus inside) | `+` `-` zoom; `0` fit |
| Minimap brush (focused) | Left/Right pan; Up/Down zoom; Home fit |

## URL

`?t=<seconds>` and `?sel=<item id>` are read once on mount and written
(history replace, debounced) on pause, on a seek while paused, and when the
selection changes. Never during playback.

## Tests and fixtures

- `npm test` (vitest, Node environment): `src/types/timeline/__tests__/`,
  `src/store/timeline/__tests__/`.
- Fixture pair: `src/types/timeline/__tests__/adSpotFixture.ts`
  (`AD_SPOT_TIMELINE`, `AD_SPOT_RECORD`, `AD_SPOT_FILMSTRIP`, `AD_SPOT_ID`).
- Browser checks against a stub API: `frontend/e2e/stub/README.md`.
