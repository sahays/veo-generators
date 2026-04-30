import { API_BASE_URL, postJson, request } from './_http'

export interface UploadInitResp {
  record_id: string
  upload_url: string
  gcs_uri: string
  content_type: string
  expires_at: string
}

export interface UploadResp {
  id: string
  gcs_uri: string
  signed_url: string
  file_type: string
}

export const assets = {
  upload: (file: File): Promise<UploadResp> => {
    const formData = new FormData()
    formData.append('file', file)
    return request<UploadResp>(`${API_BASE_URL}/assets/upload`, 'Upload failed', {
      method: 'POST',
      body: formData,
    })
  },
  initUpload: (file: File): Promise<UploadInitResp> =>
    postJson<UploadInitResp>(
      `${API_BASE_URL}/assets/upload/init`,
      {
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        file_size_bytes: file.size,
      },
      'Upload init failed',
    ),
  completeUpload: (recordId: string): Promise<UploadResp> =>
    postJson<UploadResp>(
      `${API_BASE_URL}/assets/upload/complete`,
      { record_id: recordId },
      'Upload complete failed',
    ),
  directUpload: (
    file: File,
    onProgress?: (pct: number) => void,
  ): { promise: Promise<UploadResp>; abort: () => void } => {
    let xhr: XMLHttpRequest | null = null
    const promise = (async () => {
      const init = await assets.initUpload(file)
      onProgress?.(5)
      await new Promise<void>((resolve, reject) => {
        xhr = new XMLHttpRequest()
        xhr.open('PUT', init.upload_url)
        xhr.setRequestHeader('Content-Type', init.content_type)
        // Do NOT send X-Invite-Code to GCS — it triggers CORS preflight failure.
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            // Map XHR progress to 5–90% (init=0–5, complete=90–100).
            onProgress?.(Math.round(5 + (e.loaded / e.total) * 85))
          }
        }
        xhr.onload = () => {
          if (xhr!.status >= 200 && xhr!.status < 300) resolve()
          else reject(new Error(`GCS upload failed: ${xhr!.status}`))
        }
        xhr.onerror = () => reject(new Error('Network error during upload'))
        xhr.onabort = () => reject(new Error('Upload aborted'))
        xhr.send(file)
      })
      onProgress?.(92)
      const result = await assets.completeUpload(init.record_id)
      onProgress?.(100)
      return result
    })()
    return { promise, abort: () => xhr?.abort() }
  },
}
