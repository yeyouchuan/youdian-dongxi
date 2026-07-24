const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isISODate(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DATE_PATTERN.test(value)) return false;
  const date = parseISODate(value);
  return formatISODate(date) === value;
}

export function parseISODate(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12));
}

export function formatISODate(date: Date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function formatLocalISODate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function localDateForTimestamp(value: string) {
  return formatLocalISODate(new Date(value));
}

export function todayISODate() {
  return formatLocalISODate(new Date());
}

export function addDays(value: string, amount: number) {
  const date = parseISODate(value);
  date.setUTCDate(date.getUTCDate() + amount);
  return formatISODate(date);
}

export function daysBetween(startDate: string, endDate: string) {
  const milliseconds = parseISODate(endDate).getTime() - parseISODate(startDate).getTime();
  return Math.round(milliseconds / 86_400_000);
}

export function buildDateRange(startDate: string, endDate: string) {
  const length = daysBetween(startDate, endDate) + 1;
  if (length <= 0) return [];
  return Array.from({ length }, (_, index) => addDays(startDate, index));
}

export function startOfISOWeek(value: string) {
  const date = parseISODate(value);
  const weekday = date.getUTCDay();
  const daysFromMonday = weekday === 0 ? 6 : weekday - 1;
  return addDays(value, -daysFromMonday);
}

export function endOfISOWeek(value: string) {
  return addDays(startOfISOWeek(value), 6);
}

export function formatChineseMonthDay(value: string) {
  const date = parseISODate(value);
  return `${date.getUTCMonth() + 1}月${date.getUTCDate()}日`;
}

export function weekdayLabel(value: string) {
  return ['日', '一', '二', '三', '四', '五', '六'][parseISODate(value).getUTCDay()];
}
