import * as React from 'react'
import { cn } from '@/lib/utils'

export const Skeleton = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => {
  return <div className={cn('skeleton', className)} {...props} />
}
