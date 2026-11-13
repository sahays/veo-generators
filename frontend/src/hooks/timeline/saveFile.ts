/**
 * Offer `text` as a file download. Everything is generated in the browser
 * from data already loaded; nothing is requested from the server.
 */
export function saveTextFile(filename: string, text: string, mimeType: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mimeType};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function saveJsonFile(filename: string, data: unknown): void {
  saveTextFile(filename, JSON.stringify(data, null, 2), 'application/json')
}
