import { TAGS } from '@/data/report'

export function TagRow() {
  return (
    <div className="mx-4 mt-3 flex flex-wrap gap-2">
      {TAGS.map((t, i) => (
        <span
          key={t}
          className={`rounded-full px-3.5 py-1.5 text-[13px] ${
            i === 0
              ? 'bg-white font-medium text-zinc-900'
              : 'bg-[#141418] text-zinc-400'
          }`}
        >
          {t}
        </span>
      ))}
    </div>
  )
}
