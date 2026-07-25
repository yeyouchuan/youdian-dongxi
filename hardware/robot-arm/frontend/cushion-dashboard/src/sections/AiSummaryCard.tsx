import { AI_SUMMARY, DAY, SCORE } from '@/data/report'

export function AiSummaryCard() {
  return (
    <section className="mx-4 mt-3 rounded-[20px] bg-[#141418] p-5">
      <p className="text-[11px] font-semibold tracking-[0.18em] text-sky-400/80">AI 总结</p>
      <p className="mt-2.5 text-[15px] leading-7 text-zinc-200">{AI_SUMMARY}</p>

      {/* 高亮统计行 */}
      <div className="mt-4 flex items-center justify-between rounded-xl bg-white/[0.04] px-4 py-3">
        <span className="flex items-center gap-2 text-sm text-zinc-300">
          二郎腿
          <span className="font-num font-medium text-amber-300">↑ {DAY.legCrossMinutes}分钟</span>
        </span>
        <span className="h-2 w-2 rounded-full bg-amber-400" />
      </div>

      {/* 得分构成 */}
      <div className="mt-4 space-y-2 border-t border-white/5 pt-4">
        {SCORE.breakdown.map((b) => (
          <div key={b.label} className="flex items-baseline justify-between text-[13px]">
            <span className="text-zinc-400">
              {b.label}
              <span className="ml-2 text-[11px] text-zinc-600">{b.detail}</span>
            </span>
            <span
              className={`font-num font-medium ${
                b.delta > 0 ? 'text-zinc-200' : 'text-red-400/90'
              }`}
            >
              {b.delta > 0 ? b.delta : b.delta}
            </span>
          </div>
        ))}
        <div className="flex items-baseline justify-between border-t border-white/5 pt-2 text-[13px]">
          <span className="text-zinc-300">今日得分</span>
          <span className="font-num font-semibold text-white">{SCORE.value}</span>
        </div>
      </div>
    </section>
  )
}
