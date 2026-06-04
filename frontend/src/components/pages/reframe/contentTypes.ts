// Reframe content-type metadata, shared by the create page (dropdown) and the
// landing page (card badge).

export const CONTENT_TYPE_OPTIONS = [
  { value: 'movies', label: 'Movies', description: 'Films, drama, scripted — follows characters and story' },
  { value: 'documentaries', label: 'Documentaries', description: 'Interviews, narration, b-roll — tracks speaker and subject' },
  { value: 'sports', label: 'Sports', description: 'Live action, highlights — fast tracking on the play' },
  { value: 'podcasts', label: 'Podcasts', description: 'Podcasts, interviews, panels — centers the active speaker' },
  { value: 'promos', label: 'Promos', description: 'Ads, product showcases — keeps product and presenter visible' },
  { value: 'news', label: 'News', description: 'Anchors, field reports — follows the active reporter' },
  { value: 'other', label: 'Other', description: 'General reframing for other content' },
]

export const CONTENT_TYPE_BADGE: Record<string, { label: string; className: string }> = {
  movies: { label: 'Movies', className: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
  documentaries: { label: 'Documentaries', className: 'bg-teal-500/10 text-teal-600 border-teal-500/20' },
  sports: { label: 'Sports', className: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  podcasts: { label: 'Podcasts', className: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  promos: { label: 'Promos', className: 'bg-pink-500/10 text-pink-600 border-pink-500/20' },
  news: { label: 'News', className: 'bg-red-500/10 text-red-600 border-red-500/20' },
  other: { label: 'Other', className: 'bg-gray-500/10 text-gray-600 border-gray-500/20' },
}
