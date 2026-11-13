/**
 * Background colour of each fixture segment in the generated video (`RRGGBB`),
 * in segment order. Shared by the media generator and the browser tests, which
 * read a pixel of the playing video to prove which segment is on screen.
 */
export const SEGMENT_COLOURS: readonly string[] = [
  '1F4E79', // seg 1  blue
  '7B2D26', // seg 2  brick
  '2E6B3E', // seg 3  green
  'B3541E', // seg 4  orange
  '5B2A86', // seg 5  purple
  '0E7C7B', // seg 6  teal
  'A61E4D', // seg 7  crimson
  '8A6D00', // seg 8  mustard
  '34495E', // seg 9  slate
]
