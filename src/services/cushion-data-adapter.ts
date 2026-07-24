import { healthSampleRepository } from '@/data/health-sample-repository';
import { buildDateRange } from '@/domain/date-utils';
import { buildDayReportFromStoredSegments } from '@/domain/report';
import { CushionDataAdapter } from '@/services/health-data-adapters';

export const cushionDataAdapter: CushionDataAdapter = {
  async getReport(date) {
    const segments =
      await healthSampleRepository.getRealtimePostureSegments();
    return buildDayReportFromStoredSegments(date, segments);
  },
  async getReports({ startDate, endDate }) {
    const segments =
      await healthSampleRepository.getRealtimePostureSegments();
    return buildDateRange(startDate, endDate)
      .map((date) => buildDayReportFromStoredSegments(date, segments))
      .filter((report) => report !== null);
  },
};
