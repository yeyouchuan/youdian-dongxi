import { Armchair, FileText, Home } from 'lucide-react'

const TABS = [
  { label: '首页', Icon: Home, active: false },
  { label: '坐垫', Icon: Armchair, active: false },
  { label: '报告', Icon: FileText, active: true },
]

export function TabBar() {
  return (
    <nav className="pointer-events-none sticky bottom-4 z-10 mx-auto mt-6 w-fit pb-1">
      <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-white/10 bg-[#17171b]/90 px-2 py-2 shadow-[0_12px_40px_rgba(0,0,0,0.6)] backdrop-blur">
        {TABS.map(({ label, Icon, active }) => (
          <button
            key={label}
            className={`flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] transition-colors ${
              active ? 'bg-white font-medium text-zinc-900' : 'text-zinc-400'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>
    </nav>
  )
}
