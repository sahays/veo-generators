import type { Project, StoryboardFrame } from '@/types/project'

export const SEED_PROJECTS: Project[] = [
  {
    id: 'proj-001',
    name: 'Summer Product Launch',
    prompt:
      'A dynamic product reveal sequence featuring a sleek smartphone emerging from flowing water droplets, transitioning to a rooftop sunset scene with the device held against a golden sky.',
    directorStyle: 'Christopher Nolan',
    cameraMovement: 'Dolly In',
    mood: 'Cinematic',
    location: 'Rooftop',
    videoLength: '24',
    status: 'completed',
    mediaFiles: [],
    storyboardFrames: generateStoryboardFrames(6, 'Summer Product Launch'),
    createdAt: Date.now() - 86400000 * 3,
    updatedAt: Date.now() - 86400000 * 2,
  },
  {
    id: 'proj-002',
    name: 'Brand Awareness - Urban',
    prompt:
      'Fast-paced montage of diverse city life, neon-lit streets, and dynamic street performers, ending with the brand logo appearing as a glowing hologram.',
    directorStyle: 'Ridley Scott',
    cameraMovement: 'Tracking Shot',
    mood: 'Energetic',
    location: 'Urban Street',
    videoLength: '32',
    status: 'draft',
    mediaFiles: [],
    storyboardFrames: [],
    createdAt: Date.now() - 86400000,
    updatedAt: Date.now() - 86400000,
  },
  {
    id: 'proj-003',
    name: 'Nature Retreat Promo',
    prompt:
      'Serene morning fog rolling through a mountain valley, slow reveal of a luxury cabin, warm interior shots with soft natural lighting.',
    directorStyle: 'Denis Villeneuve',
    cameraMovement: 'Crane Up',
    mood: 'Calm',
    location: 'Mountain',
    videoLength: '48',
    status: 'generating',
    mediaFiles: [],
    storyboardFrames: [],
    createdAt: Date.now() - 43200000,
    updatedAt: Date.now() - 3600000,
  },
]

export function generateStoryboardFrames(
  count: number,
  projectName: string,
): StoryboardFrame[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `frame-${i + 1}`,
    imageUrl: `https://picsum.photos/seed/${projectName.replace(/\s/g, '')}-${i}/400/225`,
    caption: getFrameCaption(i, count),
    timestamp: formatTimestamp(i, count),
  }))
}

function getFrameCaption(index: number, total: number): string {
  const captions = [
    'Opening shot — establishing scene',
    'Subject introduction with ambient lighting',
    'Dynamic transition — camera movement',
    'Key product/brand moment',
    'Emotional peak — hero shot',
    'Closing sequence with call-to-action',
    'Wide establishing shot',
    'Close-up detail shot',
    'Movement transition',
    'Final brand reveal',
  ]
  if (index === 0) return captions[0]
  if (index === total - 1) return captions[5]
  return captions[index % captions.length]
}

function formatTimestamp(index: number, total: number): string {
  const totalSeconds = 24
  const seconds = Math.round((index / (total - 1 || 1)) * totalSeconds)
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
