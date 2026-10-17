import { File as FileIcon, Image as ImageIcon, Video } from 'lucide-react'

export const FILE_TYPE_ICONS: Record<string, typeof Video> = {
  video: Video,
  image: ImageIcon,
  other: FileIcon,
}

export const FILE_TYPE_STYLES: Record<string, string> = {
  video: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  image: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  other: 'bg-gray-500/10 text-gray-600 border-gray-500/20',
}
