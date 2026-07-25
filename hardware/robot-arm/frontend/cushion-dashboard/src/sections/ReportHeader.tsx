import { ChevronDown, Share } from 'lucide-react'
import { DAY } from '@/data/report'

const WEEK = ['一', '二', '三', '四', '五', '六', '日']

export function ReportHeader() {
  return (
    <div className="px-5 pt-2">
      <div className="flex items-start justify-between">
        <div>
          <button className="flex items-center gap-1 text-[26px] font-bold leading-tight tracking-wide text-white">
            坐姿报告
            <ChevronDown className="mt-1 h-5 w-5 text-zinc-400" />
          </button>
          <p className="mt-1 text-sm text-zinc-500">{DAY.name}</p>
        </div>
        <button
          aria-label="分享"
          className="mt-1.5 flex h-9 w-9 items-center justify-center rounded-full bg-white/5 text-zinc-300"
        >
          <Share className="h-[18px] w-[18px]" />
        </button>
      </div>

      {/* 周选择器 */}
      <div className="mt-5 flex justify-between">
        {WEEK.map((d, i) => {
          const active = i === 0
          return (
            <div key={d} className="flex flex-col items-center gap-1.5">
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-full text-sm ${
                  active ? 'bg-white/10 font-semibold text-white' : 'text-zinc-500'
                }`}
              >
                {d}
              </span>
              <span className={`h-1 w-1 rounded-full ${active ? 'bg-emerald-400' : 'bg-transparent'}`} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
