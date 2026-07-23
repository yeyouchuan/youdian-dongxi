import { ManualRecordAdapter } from '@/services/health-data-adapters';

export const manualRecordAdapter: ManualRecordAdapter = {
  isSupported: () => false,
};
