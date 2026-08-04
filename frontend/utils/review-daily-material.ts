export const normalizeKeyQuotes = (value: unknown): string[] => {
  const values = Array.isArray(value) ? value : typeof value === 'string' ? [value] : []
  return [...new Set(values.filter((item): item is string => typeof item === 'string' && item.trim().length > 0))]
}
