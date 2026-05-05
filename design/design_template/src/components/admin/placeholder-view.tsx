interface PlaceholderViewProps {
  title: string
  description?: string
}

export function PlaceholderView({ title, description }: PlaceholderViewProps) {
  return (
    <div className="flex flex-1 items-center justify-center h-full">
      <div className="text-center">
        <p className="text-[14px] font-semibold text-foreground/60">{title}</p>
        {description && (
          <p className="text-[12px] text-muted-foreground mt-1">{description}</p>
        )}
      </div>
    </div>
  )
}
