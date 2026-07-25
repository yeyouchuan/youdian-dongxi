import { AXIS_END, AXIS_START, POSTURE_COLORS, SEGMENTS } from '@/data/report'

const SPAN = AXIS_END - AXIS_START

const AXIS_LABELS = [
  { at: 9 * 60, text: '09:00' },
  { at: 12 * 60, text: '12:00' },
  { at: 15 * 60, text: '15:00' },
  { at: AXIS_END, text: '18:40' },
]

// 姿态分布时间轴:按时间占比堆叠的彩色分段条
export function PostureBar() {
  return (
    <div>
      <div className="relative">
        <div className="flex h-14 w-full overflow-hidden rounded-xl">
          {SEGMENTS.map((s, i) => (
            <div
              key={i}
              title={`${s.posture}`}
              style={{
                width: `${((s.end - s.start) / SPAN) * 100}%`,
                backgroundColor: POSTURE_COLORS[s.posture],
                opacity: s.posture === '离座' ? 0.55 : 0.9,
              }}
            />
          ))}
        </div>
        {/* 时间刻度 */}
        <div className="relative mt-2 h-4">
          {AXIS_LABELS.map((l, i) => (
            <span
              key={l.text}
              className={`font-num absolute text-[11px] text-zinc-500 ${
                i === 0 ? '' : i === AXIS_LABELS.length - 1 ? '-translate-x-full' : '-translate-x-1/2'
              }`}
              style={{ left: `${((l.at - AXIS_START) / SPAN) * 100}%` }}
            >
              {l.text}
            </span>
          ))}
        </div>
      </div>
      {/* 图例 */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {(Object.keys(POSTURE_COLORS) as (keyof typeof POSTURE_COLORS)[]).map((p) => (
          <span key={p} className="flex items-center gap-1.5 text-xs text-zinc-400">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: POSTURE_COLORS[p] }}
            />
            {p}
          </span>
        ))}
      </div>
    </div>
  )
}
