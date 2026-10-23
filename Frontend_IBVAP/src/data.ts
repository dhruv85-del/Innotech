export type UploadedMedia = {
  id: string
  name: string
  kind: 'Video' | 'Image'
  size: string
  uploadedAt: string
  location: string
  duration?: string
  previewUrl?: string
  file?: File
}

export type AlertItem = {
  id: string
  title: string
  detail: string
  media: string
  location: string
  time: string
  severity: 'Critical' | 'High' | 'Medium' | 'Low'
  status: 'New' | 'Acknowledged' | 'Dismissed'
}

export const initialMedia: UploadedMedia[] = []

export const initialAlerts: AlertItem[] = []

export const activity: number[] = []
