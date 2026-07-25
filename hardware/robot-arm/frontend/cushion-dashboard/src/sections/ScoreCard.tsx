import { ChevronRight } from 'lucide-react'
import { ScoreGauge } from '@/components/ScoreGauge'
import { DAY, SCORE } from '@/data/report'

const SUB_METRICS = [
  { label: '坐姿端正', value: `${DAY.uprightPct}%`, ok: true },
  { label: '起身活动', value: `${DAY.standCount}次`, ok: true },
  { label: '久坐时长', value: DAY.seatedText, ok: false },
]

export function ScoreCard() {
  return (
    <section className="mx-4 mt-4 rounded-[20px] bg-[#141418] p-5">
      {/* 仪表盘 + 分数 */}
      <div className="relative">
        <ScoreGauge value={SCORE.value} />
        <div className="absolute inset-x-0 top-[46%] flex flex-col items-center">
          <span className="font-num text-[64px] font-extralight leading-none tracking-tight text-white">
            {SCORE.value}
          </span>
          <span className="mt-2.5 flex items-center gap-1.5 text-[13px] text-zinc-400">
            {SCORE.status}
            <span className={`h-1.5 w-1.5 rounded-full ${SCORE.ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
          </span>
        </div>
      </div>

      {/* 标题行 */}
      <div className="mt-1 flex items-center justify-center gap-1 text-[15px] font-medium text-zinc-200">
        坐姿健康得分
        <ChevronRight className="h-4 w-4 text-zinc-500" />
      </div>
      <p className="mt-1 text-center text-xs text-zinc-500">{DAY.date}</p>
      <p className="mt-2 text-center text-[11px] text-zinc-600">
        主要扣分:{SCORE.mainDrag}
      </p>

      {/* 三项子指标 */}
      <div className="mt-5 grid grid-cols-3 divide-x divide-white/5 border-t border-white/5 pt-4">
        {SUB_METRICS.map((m) => (
          <button key={m.label} className="flex flex-col items-center gap-1">
            <span className="flex items-center gap-0.5 text-xs text-zinc-500">
              {m.label}
              <ChevronRight className="h-3 w-3" />
            </span>
            <span className="flex items-center gap-1.5 text-[15px] font-medium text-zinc-100">
              <span className={`h-1.5 w-1.5 rounded-full ${m.ok ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              {m.value}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
