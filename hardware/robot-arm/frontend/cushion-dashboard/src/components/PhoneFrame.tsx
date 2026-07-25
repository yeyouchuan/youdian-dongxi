import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

function StatusBar() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15_000)
    return () => window.clearInterval(id)
  }, [])
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`

  return (
    <div className="flex h-12 items-center justify-between px-7 pt-2 text-[13px] font-semibold text-white">
      <span className="font-num tracking-wide">{time}</span>
      {/* 灵动岛 */}
      <span className="absolute left-1/2 top-3 h-[22px] w-[96px] -translate-x-1/2 rounded-full bg-black" />
      <span className="flex items-center gap-1.5">
        {/* 信号 */}
        <svg width="17" height="11" viewBox="0 0 17 11" fill="white" aria-hidden>
          <rect x="0" y="7" width="3" height="4" rx="0.8" />
          <rect x="4.5" y="5" width="3" height="6" rx="0.8" />
          <rect x="9" y="2.5" width="3" height="8.5" rx="0.8" />
          <rect x="13.5" y="0" width="3" height="11" rx="0.8" />
        </svg>
        <span className="text-[12px] font-medium">5G</span>
        {/* 电池 */}
        <svg width="25" height="12" viewBox="0 0 25 12" aria-hidden>
          <rect x="0.5" y="0.5" width="20" height="11" rx="3" fill="none" stroke="white" strokeOpacity="0.4" />
          <rect x="2" y="2" width="14" height="8" rx="1.6" fill="white" />
          <path d="M23 4v4c1.1-.3 1.8-1 1.8-2S24.1 4.3 23 4z" fill="white" fillOpacity="0.4" />
        </svg>
      </span>
    </div>
  )
}

export function PhoneFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#050507] sm:py-8">
      {/* 桌面氛围光 */}
      <div
        className="pointer-events-none fixed inset-0 hidden sm:block"
        style={{
          background:
            'radial-gradient(50% 40% at 50% 0%, rgba(52,211,153,0.05), transparent), radial-gradient(40% 30% at 80% 100%, rgba(56,189,248,0.04), transparent)',
        }}
      />
      {/* 机身 */}
      <div className="relative w-full max-w-[400px] sm:rounded-[52px] sm:bg-[#1c1c21] sm:p-[10px] sm:shadow-[0_40px_120px_-20px_rgba(0,0,0,0.9),0_0_0_1px_rgba(255,255,255,0.08)]">
        {/* 侧边按键装饰 */}
        <span className="absolute -left-[2px] top-28 hidden h-10 w-[3px] rounded-l bg-[#2a2a30] sm:block" />
        <span className="absolute -left-[2px] top-44 hidden h-14 w-[3px] rounded-l bg-[#2a2a30] sm:block" />
        <span className="absolute -right-[2px] top-36 hidden h-16 w-[3px] rounded-r bg-[#2a2a30] sm:block" />
        {/* 屏幕 */}
        <div className="relative h-dvh overflow-hidden bg-[#0a0a0c] sm:h-[824px] sm:rounded-[44px]">
          <div className="relative">
            <StatusBar />
          </div>
          <div className="h-[calc(100%-48px)] overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
