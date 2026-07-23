import { appleHealthAdapter } from '@/services/apple-health-adapter';
import { cushionDataAdapter } from '@/services/cushion-data-adapter';
import { HealthDataService } from '@/services/health-data-adapters';
import { manualRecordAdapter } from '@/services/manual-record-adapter';

export const healthDataService: HealthDataService = {
  cushion: cushionDataAdapter,
  appleHealth: appleHealthAdapter,
  manual: manualRecordAdapter,
};
