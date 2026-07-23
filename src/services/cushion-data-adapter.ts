import {
  getDemoReport,
  getDemoReports,
} from '@/data/demo-report-series';
import { CushionDataAdapter } from '@/services/health-data-adapters';

export const cushionDataAdapter: CushionDataAdapter = {
  async getReport(date) {
    return getDemoReport(date);
  },
  async getReports({ startDate, endDate }) {
    return getDemoReports(startDate, endDate);
  },
};
