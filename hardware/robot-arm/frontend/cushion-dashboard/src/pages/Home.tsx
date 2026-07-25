import { PhoneFrame } from '@/components/PhoneFrame'
import { ReportHeader } from '@/sections/ReportHeader'
import { ScoreCard } from '@/sections/ScoreCard'
import { AiSummaryCard } from '@/sections/AiSummaryCard'
import { TimelineCard } from '@/sections/TimelineCard'
import { BiometricsCard } from '@/sections/BiometricsCard'
import { TagRow } from '@/sections/TagRow'
import { TabBar } from '@/sections/TabBar'

export default function Home() {
  return (
    <PhoneFrame>
      <div className="pb-2">
        <ReportHeader />
        <ScoreCard />
        <AiSummaryCard />
        <TimelineCard />
        <BiometricsCard />
        <TagRow />
      </div>
      <TabBar />
    </PhoneFrame>
  )
}
