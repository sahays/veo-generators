/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_GUEST_INVITE_CODE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
