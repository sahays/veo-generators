import type { Project } from '@/types/project'

export const SEED_PROJECTS: Project[] = [
  {
    id: 'proj-001',
    name: 'Cyberpunk Tokyo Chase',
    type: 'movie',
    base_concept: 'A high-speed motorcycle chase through the neon-lit streets of 2077 Tokyo, ending in a dramatic jump over a broken bridge.',
    video_length: '24',
    orientation: '16:9',
    status: 'completed',
    scenes: [
      {
        id: 's1',
        visual_description: 'Wide shot of the motorcycle weaving through heavy traffic. Neon signs blur in the background.',
        timestamp_start: '00:00',
        timestamp_end: '00:06',
        metadata: { 
          location: 'Neo-Shinjuku', 
          lighting: 'Neon Blue & Pink', 
          camera_angle: 'Low tracking shot',
          character: 'Kael in leather gear',
          mood: 'High-octane'
        },
        thumbnail_url: 'https://picsum.photos/seed/cyber1/800/450',
        tokens_consumed: { input: 150, output: 500 }
      },
      {
        id: 's2',
        visual_description: 'Extreme close-up of Kael eyes reflecting the city lights through the visor.',
        timestamp_start: '00:06',
        timestamp_end: '00:10',
        metadata: { 
          location: 'Interior Helmet', 
          lighting: 'Reflected Neon', 
          camera_angle: 'Extreme Close-up',
          character: 'Kael',
          mood: 'Intense'
        },
        thumbnail_url: 'https://picsum.photos/seed/cyber2/800/450',
        tokens_consumed: { input: 80, output: 300 }
      },
      {
        id: 's3',
        visual_description: 'The motorcycle launches off a ramp. Slow motion as it clears the gap.',
        timestamp_start: '00:10',
        timestamp_end: '00:18',
        metadata: { 
          location: 'Broken Skyway', 
          lighting: 'Backlit by moon', 
          camera_angle: 'Side profile',
          mood: 'Epic'
        },
        thumbnail_url: 'https://picsum.photos/seed/cyber3/800/450',
        tokens_consumed: { input: 200, output: 650 }
      }
    ],
    usage: { total_input_tokens: 430, total_output_tokens: 1450, estimated_cost_usd: 0.028 },
    createdAt: Date.now() - 86400000 * 3,
    updatedAt: Date.now() - 86400000 * 2,
  },
  {
    id: 'proj-002',
    name: 'Artisan Coffee Craft',
    type: 'advertizement',
    base_concept: 'A slow, sensory advertisement for a premium coffee brand, focusing on the texture of beans and the steam of the pour.',
    video_length: '16',
    orientation: '9:16',
    status: 'scripted',
    scenes: [
      {
        id: 's1',
        visual_description: 'Macroscopic view of roasted beans falling into a grinder.',
        timestamp_start: '00:00',
        timestamp_end: '00:04',
        metadata: { 
          location: 'Rustic Cafe', 
          lighting: 'Soft Warm', 
          camera_angle: 'Macro',
          mood: 'Elegant'
        },
        thumbnail_url: 'https://picsum.photos/seed/coffee1/800/450',
        tokens_consumed: { input: 100, output: 400 }
      },
      {
        id: 's2',
        visual_description: 'Slow motion pour of milk into espresso, forming a heart.',
        timestamp_start: '00:04',
        timestamp_end: '00:10',
        metadata: { 
          location: 'Countertop', 
          lighting: 'Natural side light', 
          camera_angle: 'Top-down',
          mood: 'Comforting'
        },
        thumbnail_url: 'https://picsum.photos/seed/coffee2/800/450',
        tokens_consumed: { input: 90, output: 350 }
      }
    ],
    usage: { total_input_tokens: 190, total_output_tokens: 750, estimated_cost_usd: 0.012 },
    createdAt: Date.now() - 86400000,
    updatedAt: Date.now() - 86400000,
  }
]

export function generateStoryboardFrames(
  count: number,
  projectName: string,
): any[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `frame-${i + 1}`,
    imageUrl: `https://picsum.photos/seed/${projectName.replace(/\s/g, '')}-${i}/400/225`,
    caption: 'Scene breakdown',
    timestamp: '00:00',
  }))
}
