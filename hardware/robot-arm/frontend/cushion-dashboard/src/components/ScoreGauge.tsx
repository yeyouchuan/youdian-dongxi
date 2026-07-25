interface Props {
  value: number // 0..100
}

// 半圆刻度仪表:48 根小刻度,按得分点亮,青 → 绿渐变
const TICKS = 48

export function ScoreGauge({ value }: Props) {
  const cx = 150
  const cy = 150
  const rOuter = 128
  const rInner = 100
  const lit = Math.round((value / 100) * TICKS)

  const ticks = []
  for (let i = 0; i < TICKS; i++) {
    // 从左端 180° 扫到右端 0°
    const angle = Math.PI - (i / (TICKS - 1)) * Math.PI
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    const on = i < lit
    // 渐变:左端青 #22d3ee → 右端绿 #34d399
    const k = i / (TICKS - 1)
    const r = Math.round(34 + (52 - 34) * k)
    const g = Math.round(211 + (211 - 211) * k)
    const b = Math.round(238 + (153 - 238) * k)
    ticks.push(
      <line
        key={i}
        x1={cx + rInner * cos}
        y1={cy - rInner * sin}
        x2={cx + rOuter * cos}
        y2={cy - rOuter * sin}
        stroke={on ? `rgb(${r},${g},${b})` : 'rgba(255,255,255,0.08)'}
        strokeWidth={i === lit - 1 ? 5 : 3.5}
        strokeLinecap="round"
        opacity={on ? 0.55 + 0.45 * (i / Math.max(1, lit - 1)) : 1}
      />,
    )
  }

  return (
    <svg viewBox="0 0 300 160" className="w-full">
      {ticks}
    </svg>
  )
}
