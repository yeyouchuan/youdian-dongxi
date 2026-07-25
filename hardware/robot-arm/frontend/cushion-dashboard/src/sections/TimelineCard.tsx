import { PostureBar } from '@/components/PostureBar'
import { DAY } from '@/data/report'

function hm(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h}小时${m > 0 ? `${m}分` : ''}` : `${m}分钟`
}

export function TimelineCard() {
  const upright = DAY.totals.find((t) => t.posture === '正坐')
  const legCross = DAY.totals.find((t) => t.posture === '二郎腿')

  return (
    <section className="mx-4 mt-3 rounded-[20px] bg-[#141418] p-5">
      <p className="text-[15px] font-medium text-zinc-200">姿态分布</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
        <span className="text-zinc-400">
          正坐 <span className="font-num text-zinc-100">{upright ? hm(upright.minutes) : '—'}</span>
          <span className="font-num ml-1.5 text-zinc-500">{upright?.pct}%</span>
        </span>
        <span className="text-zinc-400">
          二郎腿 <span className="font-num text-amber-300">{legCross ? hm(legCross.minutes) : '—'}</span>
          <span className="font-num ml-1.5 text-zinc-500">{legCross?.pct}%</span>
        </span>
      </div>
      <div className="mt-4">
        <PostureBar />
      </div>
    </section>
  )
}
