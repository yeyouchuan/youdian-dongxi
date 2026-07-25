import { ChevronRight } from 'lucide-react'
import { BIOMETRICS } from '@/data/report'

export function BiometricsCard() {
  return (
    <section className="mx-4 mt-3 rounded-[20px] bg-[#141418] p-5">
      <p className="text-[15px] font-medium text-zinc-200">生物特征数据</p>
      <div className="mt-1 divide-y divide-white/5">
        {BIOMETRICS.map((b) => (
          <button key={b.label} className="flex w-full items-center justify-between py-3.5">
            <span className="flex items-center gap-1 text-sm text-zinc-400">
              {b.label}
              <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
            </span>
            <span className="flex flex-col items-end">
              <span className="flex items-baseline gap-1.5">
                <span
                  className={`h-1.5 w-1.5 self-center rounded-full ${
                    b.tone === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'
                  }`}
                />
                <span className="font-num text-xl font-light text-white">{b.value}</span>
                <span className="text-xs text-zinc-500">{b.unit}</span>
              </span>
              <span className="mt-0.5 text-[11px] text-zinc-600">{b.caption}</span>
            </span>
          </button>
        ))}
      </div>
      <p className="pt-2 text-[11px] text-zinc-600">* 静坐状态下更准确</p>
    </section>
  )
}
