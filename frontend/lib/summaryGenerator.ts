import { DataRow, Intent } from "./types";

export function generateSummary(data: DataRow[], intent: Intent, userQuestion?: string): string {
  if (!data || data.length === 0) {
    return "No data available for analysis.";
  }

  const keys = Object.keys(data[0]);
  const metricKeys = keys.slice(1);

  // Single value case (count queries)
  if (keys.length === 1 || metricKeys.length === 0) {
    const value = data[0][keys[0]];
    const formattedValue = typeof value === "number" ? value.toLocaleString() : value;
    return generateCountSummary(formattedValue, userQuestion);
  }

  // Multi-column data analysis
  const dimensionKey = keys[0];
  const primaryMetric = metricKeys[0];

  switch (intent) {
    case "distribution":
      return generateDistributionSummary(data, dimensionKey, primaryMetric, userQuestion);

    case "trend":
      return generateTrendSummary(data, dimensionKey, primaryMetric, userQuestion);

    case "topN":
      return generateRankingSummary(data, dimensionKey, primaryMetric, userQuestion);

    case "mutation_prevalence":
      return generatePrevalenceSummary(data, dimensionKey, primaryMetric, userQuestion);

    case "cohort_comparison":
      return generateComparisonSummary(data, dimensionKey, primaryMetric, userQuestion);

    default:
      return generateGeneralSummary(data, dimensionKey, primaryMetric, userQuestion);
  }
}

function generateCountSummary(value: string, userQuestion?: string): string {
  // For count queries, provide a direct answer
  return `The total number is ${value}.`;
}

function generateDistributionSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  // Sort by metric value descending
  const sorted = [...data].sort((a, b) => (b[metricKey] as number) - (a[metricKey] as number));

  const total = sorted.reduce((sum, item) => sum + (item[metricKey] as number), 0);
  const topItem = sorted[0];
  const topPercentage = ((topItem[metricKey] as number) / total * 100).toFixed(1);

  if (sorted.length === 1) {
    return `${topItem[dimensionKey]} has ${topItem[metricKey]} records (${topPercentage}% of total).`;
  }

  const secondItem = sorted[1];
  return `${topItem[dimensionKey]} leads with ${topItem[metricKey]} records (${topPercentage}%), followed by ${secondItem[dimensionKey]} with ${secondItem[metricKey]}.`;
}

function generateTrendSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  // Assume data is sorted by time dimension
  const values = data.map(item => item[metricKey] as number);
  const firstValue = values[0];
  const lastValue = values[values.length - 1];
  const change = lastValue - firstValue;
  const changePercent = ((change / firstValue) * 100).toFixed(1);

  const direction = change > 0 ? "increased" : change < 0 ? "decreased" : "remained stable";
  const absChange = Math.abs(change);

  return `The data shows a ${direction} trend from ${firstValue} to ${lastValue} (${changePercent}% change, ${absChange} total).`;
}

function generateRankingSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  const sorted = [...data].sort((a, b) => (b[metricKey] as number) - (a[metricKey] as number));
  const top3 = sorted.slice(0, 3);

  const rankings = top3.map((item, index) =>
    `${index + 1}. ${item[dimensionKey]} (${item[metricKey]})`
  ).join(", ");

  return `The top rankings are: ${rankings}`;
}

function generatePrevalenceSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  const sorted = [...data].sort((a, b) => (b[metricKey] as number) - (a[metricKey] as number));
  const total = sorted.reduce((sum, item) => sum + (item[metricKey] as number), 0);

  const topItem = sorted[0];
  const prevalence = ((topItem[metricKey] as number) / total * 100).toFixed(1);

  return `The most prevalent is ${topItem[dimensionKey]} (${prevalence}% of cases, ${topItem[metricKey]} total).`;
}

function generateComparisonSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  const sorted = [...data].sort((a, b) => (b[metricKey] as number) - (a[metricKey] as number));

  const highest = sorted[0];
  const lowest = sorted[sorted.length - 1];
  const ratio = ((highest[metricKey] as number) / (lowest[metricKey] as number)).toFixed(1);

  return `${highest[dimensionKey]} shows the highest values (${highest[metricKey]}), ${ratio}x higher than ${lowest[dimensionKey]} (${lowest[metricKey]}).`;
}

function generateGeneralSummary(data: DataRow[], dimensionKey: string, metricKey: string, userQuestion?: string): string {
  const totalRecords = data.length;
  const totalValue = data.reduce((sum, item) => sum + (item[metricKey] as number), 0);
  const avgValue = (totalValue / totalRecords).toFixed(1);

  return `Across ${totalRecords} records, the average value is ${avgValue}.`;
}