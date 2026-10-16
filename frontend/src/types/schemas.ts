import { z } from 'zod'

export const inviteCodeFormSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, 'Invite code is required')
    .max(128, 'Invite code is too long'),
})

export type InviteCodeFormValues = z.infer<typeof inviteCodeFormSchema>

export const systemResourceFormSchema = z
  .object({
    type: z.enum(['prompt', 'schema']),
    name: z.string().trim().min(2, 'Name must be at least 2 characters').max(120),
    category: z.string().trim().min(1, 'Category is required'),
    content: z.string().trim().min(5, 'Content must be at least 5 characters'),
  })
  .superRefine((val, ctx) => {
    if (val.type === 'schema') {
      try {
        JSON.parse(val.content)
      } catch {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['content'],
          message: 'Schema content must be valid JSON',
        })
      }
    }
  })

export type SystemResourceFormValues = z.infer<typeof systemResourceFormSchema>

export const promoCreateSchema = z.object({
  gcs_uri: z.string().min(1, 'Please select a source video'),
  source_filename: z.string().min(1),
  prompt_id: z.string().optional(),
  target_duration: z.number().int().min(15).max(600),
  text_overlay: z.boolean(),
  generate_thumbnail: z.boolean(),
  model_id: z.string().optional(),
  region: z.string().optional(),
})

export const reframeCreateSchema = z.object({
  gcs_uri: z.string().min(1, 'Please select a landscape source video'),
  source_filename: z.string().min(1),
  diagnostic_mode: z.boolean(),
  output_aspect_ratio: z.enum(['9:16', '3:4']),
  model_id: z.string().optional(),
  region: z.string().optional(),
})

export const adaptCreateSchema = z.object({
  gcs_uri: z.string().min(1, 'Please select a source image'),
  source_filename: z.string().min(1),
  source_mime_type: z.string().min(1),
  template_gcs_uri: z.string().optional(),
  aspect_ratios: z.array(z.string()).min(1, 'Select at least one aspect ratio'),
  model_id: z.string().optional(),
  region: z.string().optional(),
})
