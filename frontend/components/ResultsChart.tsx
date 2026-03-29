"use client";

import React, { Component, ReactNode } from "react";
import { VegaEmbed } from "react-vega";
import { DataRow } from "@/lib/types";
import { AlertCircle } from "lucide-react";

const COLORS = [
  "#0088FE",
  "#00C49F",
  "#FFBB28",
  "#FF8042",
  "#8884d8",
  "#82ca9d",
];

// Error boundary to catch Vega-Lite render failures gracefully
class ChartErrorBoundary extends Component<
  { children: ReactNode; fallbackData: DataRow[] },
  { hasError: boolean; errorMessage: string }
> {
  constructor(props: { children: ReactNode; fallbackData: DataRow[] }) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, errorMessage: error.message };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full space-y-2 text-gray-400">
          <AlertCircle className="w-6 h-6 text-amber-400" />
          <p className="text-xs text-amber-600 font-medium">
            Chart could not be rendered
          </p>
          <p className="text-[10px] text-gray-400">{this.state.errorMessage}</p>
          <p className="text-[10px] text-gray-400">
            Data is shown in the table below
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

interface ResultsChartProps {
  data: DataRow[];
  // Match backend exactly
  type: "bar" | "line" | "metric" | "table" | string;
}

export function ResultsChart({ data, type }: ResultsChartProps) {
  if (!data || data.length === 0) return null;

  const keys = Object.keys(data[0]);
  const metricKeys = keys.slice(1);

  let dimensionKey: string;
  let primaryMetric: string;

  if (type === "metric" || metricKeys.length === 0) {
    primaryMetric = keys[0];
    dimensionKey = "";
  } else {
    dimensionKey = keys[0];
    primaryMetric = metricKeys[0];
  }

  // Detect single-row wide format with percentage pairs
  // e.g. {total_tested_patients, patients_with_kras, kras_percentage, ...}
  // Transform to long format for bar chart with percentage labels
  const isSingleRowWide = data.length === 1 && keys.length > 3;
  const pctKeys = keys.filter(
    (k) =>
      k.endsWith("_percentage") ||
      k.endsWith("_pct") ||
      k.endsWith("_proportion"),
  );
  const totalKey = keys.find((k) => k.startsWith("total_"));

  const formatValue = (key: string, val: number): string => {
    if (
      key.includes("year") ||
      key.includes("date") ||
      key === "age_group_start" ||
      key.includes("_id")
    ) {
      return val.toString();
    }
    if (
      key.includes("proportion") ||
      key.includes("pct") ||
      key.includes("percentage")
    ) {
      return `${(val * (val <= 1 ? 100 : 1)).toFixed(1)}%`;
    }
    return val.toLocaleString();
  };

  const renderChart = () => {
    // Fallback: single row, single column → always metric card regardless of type
    // agent1 ten
    if (data.length === 1 && keys.length === 1) {
      const value = data[0][keys[0]];
      return (
        <div className="flex items-center justify-center w-full h-64 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100 p-8">
          <div className="text-center">
            <p className="text-sm text-gray-500 uppercase tracking-widest font-semibold mb-4">
              Result
            </p>
            <p className="text-6xl font-bold text-blue-600 mb-2">
              {typeof value === "number" ? formatValue(keys[0], value) : value}
            </p>
            <p className="text-xs text-gray-400 uppercase tracking-widest">
              {keys[0].replace(/_/g, " ")}
            </p>
          </div>
        </div>
      );
    }

    // --- Wide-to-long transform (mutation prevalence / multi-attribute pivot) ---
    if (isSingleRowWide && pctKeys.length > 1 && type === "metric") {
      const longData = pctKeys.map((pctKey) => {
        const label = pctKey
          .replace(/_percentage$|_pct$|_proportion$/, "")
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c) => c.toUpperCase());

        // Extract base name to find paired count key
        // e.g. kras_percentage → kras → finds patients_with_kras
        const baseName = pctKey.replace(/_percentage$|_pct$|_proportion$/, "");

        const countKey = keys.find(
          (k) =>
            k !== pctKey &&
            k !== totalKey &&
            !k.endsWith("_percentage") &&
            !k.endsWith("_pct") &&
            !k.endsWith("_proportion") &&
            !k.startsWith("total_") &&
            (k.endsWith(`_${baseName}`) ||
              k.includes(`_${baseName}_`) ||
              k === baseName),
        );

        return {
          attribute: label,
          patient_count: countKey ? (data[0][countKey] as number) : 0,
          percentage: data[0][pctKey] as number,
        };
      });

      const totalValue = totalKey ? (data[0][totalKey] as number) : null;

      const wideSpec: any = {
        $schema: "https://vega.github.io/schema/vega-lite/v6.json",
        data: { values: longData },
        width: "container" as const,
        height: "container" as const,
        background: "transparent",
        layer: [
          {
            mark: { type: "bar", tooltip: true, cornerRadiusEnd: 4 },
            encoding: {
              x: {
                field: "attribute",
                type: "nominal",
                title: null,
                axis: { labelAngle: 0 },
              },
              y: {
                field: "patient_count",
                type: "quantitative",
                title: "Patient Count",
                axis: { titleColor: COLORS[0] },
              },
              color: {
                field: "attribute",
                type: "nominal",
                scale: { range: COLORS },
                legend: null,
              },
              tooltip: [
                { field: "attribute", type: "nominal" },
                {
                  field: "patient_count",
                  type: "quantitative",
                  title: "Patients",
                },
                { field: "percentage", type: "quantitative", title: "%" },
              ],
            },
          },
          {
            mark: {
              type: "text",
              align: "center",
              baseline: "bottom",
              dy: -5,
              fontSize: 11,
              fontWeight: "bold",
            },
            encoding: {
              x: { field: "attribute", type: "nominal" },
              y: { field: "patient_count", type: "quantitative" },
              text: {
                field: "percentage",
                type: "quantitative",
                format: ".1f",
              },
              color: { value: "#666" },
            },
          },
        ],
        config: {
          view: { stroke: "transparent" },
          axis: { grid: false, domain: false, ticks: false, labelPadding: 10 },
        },
      };

      return (
        <div className="w-full mt-4 bg-white/50 backdrop-blur-sm rounded-xl p-4 border border-gray-100 shadow-sm overflow-hidden">
          {totalKey && (
            <div className="text-center mb-2">
              <span className="text-xs text-gray-500 uppercase tracking-widest font-semibold">
                {totalKey
                  .replace(/_/g, " ")
                  .replace(/\b\w/g, (c) => c.toUpperCase())}
                :
              </span>
              <span className="text-sm font-bold text-blue-600 ml-2">
                {totalValue !== null
                  ? formatValue(totalKey ?? "", totalValue)
                  : ""}
              </span>
            </div>
          )}
          <div className="w-full h-56">
            <ChartErrorBoundary fallbackData={data}>
              <VegaEmbed
                spec={wideSpec}
                options={{ actions: false }}
                style={{ width: "100%", height: "100%" }}
              />
            </ChartErrorBoundary>
          </div>
        </div>
      );
    }

    // --- Standard chart types ---
    let spec: Record<string, unknown> = {
      $schema: "https://vega.github.io/schema/vega-lite/v6.json",
      data: { values: data },
      width: "container",
      height: "container",
      autosize: { type: "fit", contains: "padding" },
      background: "transparent",
      config: {
        view: { stroke: "transparent" },
        axis: {
          grid: false,
          domain: false,
          ticks: false,
          labelPadding: 10,
        },
        legend: {
          orient: "bottom",
          title: null,
        },
      },
    };

    // Fallback: metric type but multiple rows → render as bar chart
    // Handles cases where Agent1 classifies multi-row results as 'count'
    // e.g. count by year returns 2 rows but was classified as count intent
    if (type === "metric" && data.length > 1) {
      const isYearDimension =
        keys[0].includes("year") || keys[0].includes("date");
      const chartType = isYearDimension && data.length > 3 ? "line" : "bar";

      // Detect all numeric columns and use first one for y-axis:
      const numericCols = keys
        .slice(1)
        .filter((k) => typeof data[0][k] === "number");
      const yField = numericCols[0] ?? keys[1];

      const multiRowSpec: any = {
        $schema: "https://vega.github.io/schema/vega-lite/v6.json",
        data: { values: data },
        width: "container" as const,
        height: "container" as const,
        background: "transparent",
        mark: {
          type: chartType,
          tooltip: true,
          ...(chartType === "bar"
            ? { cornerRadiusEnd: 4 }
            : { point: true, strokeWidth: 2 }),
        },
        encoding: {
          x: {
            field: keys[0],
            type: "ordinal",
            title: null,
            axis: { labelAngle: 0 },
          },
          y: {
            field: yField,
            type: "quantitative",
            title: null,
            scale: { zero: true },
          },
          color:
            chartType === "bar"
              ? {
                  field: keys[0],
                  type: "nominal",
                  scale: { range: COLORS },
                  legend: null,
                }
              : { value: COLORS[0] },
          tooltip: keys.map((k) => ({
            field: k,
            type: typeof data[0][k] === "number" ? "quantitative" : "nominal",
            title: k.replace(/_/g, " "),
          })),
        },
        config: {
          view: { stroke: "transparent" },
          axis: { grid: false, domain: false, ticks: false, labelPadding: 10 },
          axisY: { grid: true, gridDash: [3, 3] },
        },
      };

      return (
        <ChartErrorBoundary fallbackData={data}>
          <VegaEmbed
            spec={multiRowSpec}
            options={{ actions: false }}
            style={{ width: "100%", height: "100%" }}
          />
        </ChartErrorBoundary>
      );
    }

    switch (type) {
      case "pie":
        spec = {
          ...spec,
          mark: { type: "arc", innerRadius: 0, outerRadius: 80, tooltip: true },
          encoding: {
            theta: { field: primaryMetric, type: "quantitative" },
            color: {
              field: dimensionKey,
              type: "nominal",
              scale: { range: COLORS },
            },
            tooltip: [
              { field: dimensionKey, type: "nominal" },
              { field: primaryMetric, type: "quantitative" },
            ],
          },
        };
        break;

      case "line":
        const isMultiSeries = keys.length === 3;
        const seriesKey = isMultiSeries ? keys[1] : null;
        const lineMetric = isMultiSeries ? keys[2] : primaryMetric;

        spec = {
          ...spec,
          config: {
            ...(spec.config as object),
            axisY: { grid: true, gridDash: [3, 3] }, // Y grid only
          },
          mark: { type: "line", point: true, tooltip: true, strokeWidth: 2 },
          encoding: {
            x: { field: dimensionKey, type: "ordinal", title: null },
            y: {
              field: lineMetric,
              type: "quantitative" as const,
              title: null,
            },
            ...(isMultiSeries
              ? {
                  color: {
                    field: seriesKey,
                    type: "nominal" as const,
                    scale: { range: COLORS },
                  },
                  tooltip: [
                    { field: dimensionKey, type: "ordinal" },
                    { field: seriesKey, type: "nominal" },
                    { field: lineMetric, type: "quantitative" },
                  ],
                }
              : {
                  color: { value: COLORS[0] },
                  tooltip: [
                    { field: dimensionKey, type: "nominal" },
                    { field: lineMetric, type: "quantitative" },
                  ],
                }),
          },
        };
        break;

      case "stacked":
        // Stacked bar: requires 2 dimensions + 1 metric
        // uses second key as the stack group, first key as x-axis
        const stackGroupKey = keys[1] ?? dimensionKey;
        const stackMetric = keys[2] ?? primaryMetric;
        spec = {
          ...spec,
          config: {
            ...(spec.config as object),
            axisY: { grid: true, gridDash: [3, 3] },
          },
          mark: { type: "bar", tooltip: true },
          encoding: {
            x: {
              field: dimensionKey,
              type: "nominal",
              title: null,
              axis: { labelAngle: 0 },
            },
            y: {
              field: stackMetric,
              type: "quantitative",
              title: null,
              stack: "zero",
            },
            color: {
              field: stackGroupKey,
              type: "nominal",
              scale: { range: COLORS },
            },
            tooltip: [
              { field: dimensionKey, type: "nominal" },
              { field: stackGroupKey, type: "nominal" },
              { field: stackMetric, type: "quantitative" },
            ],
          },
        };
        break;

      case "metric":
        // Handle multiple scalar metrics - show as side-by-side cards
        if (keys.length > 1) {
          return (
            <div className="flex flex-wrap gap-4 items-center justify-center w-full bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100 p-8">
              {keys.map((key, i) => {
                const val = data[0]?.[key] ?? 0;
                return (
                  <div key={key} className="text-center px-6">
                    <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold mb-2">
                      {key.replace(/_/g, " ")}
                    </p>
                    <p
                      className={`font-bold text-blue-600 mb-1 ${keys.length > 3 ? "text-3xl" : "text-5xl"}`}
                    >
                      {typeof val === "number" ? formatValue(key, val) : val}
                    </p>
                  </div>
                );
              })}
            </div>
          );
        }
        // Single metric - original behaviour
        const value = data[0]?.[primaryMetric] ?? 0;
        return (
          <div className="flex items-center justify-center w-full h-64 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100 p-8">
            <div className="text-center">
              <p className="text-sm text-gray-500 uppercase tracking-widest font-semibold mb-4">
                Result
              </p>
              <p className="text-6xl font-bold text-blue-600 mb-2">
                {typeof value === "number"
                  ? formatValue(primaryMetric, value)
                  : value}
              </p>
              <p className="text-xs text-gray-400 uppercase tracking-widest">
                {primaryMetric}
              </p>
            </div>
          </div>
        );
        break;

      case "bar":
      default: {
        // Detect cohort comparison: 2+ dimension columns before the metric
        // e.g. [gender, age_group, count_patients] → grouped bar chart
        const numericKeys = keys.filter((k) => typeof data[0][k] === "number");
        const dimensionKeys = keys.filter((k) => !numericKeys.includes(k));
        const isGrouped = dimensionKeys.length >= 2;

        if (isGrouped) {
          // Grouped bar chart: x = first dimension, color = second dimension
          const xDim = dimensionKeys[0];
          const colorDim = dimensionKeys[1];
          const metric = numericKeys[0] ?? primaryMetric;

          spec = {
            ...spec,
            config: {
              ...(spec.config as object),
              axisY: { grid: true, gridDash: [3, 3] },
            },
            mark: { type: "bar", tooltip: true, cornerRadiusEnd: 3 },
            encoding: {
              x: {
                field: xDim,
                type: "nominal",
                title: null,
                axis: { labelAngle: -30 },
              },
              xOffset: {
                // side-by-side grouping within each x category
                field: colorDim,
                type: "nominal",
              },
              y: {
                field: metric,
                type: "quantitative",
                title: null,
              },
              color: {
                field: colorDim,
                type: "nominal",
                scale: { range: COLORS },
                legend: { title: colorDim.replace(/_/g, " ") },
              },
              tooltip: [
                {
                  field: xDim,
                  type: "nominal",
                  title: xDim.replace(/_/g, " "),
                },
                {
                  field: colorDim,
                  type: "nominal",
                  title: colorDim.replace(/_/g, " "),
                },
                {
                  field: metric,
                  type: "quantitative",
                  title: metric.replace(/_/g, " "),
                },
              ],
            },
          };
        } else {
          // Simple single-dimension bar chart (original behaviour)
          spec = {
            ...spec,
            config: {
              ...(spec.config as object),
              axisY: { grid: true, gridDash: [3, 3] },
            },
            mark: { type: "bar", tooltip: true, cornerRadiusEnd: 4 },
            encoding: {
              x: {
                field: dimensionKey,
                type: "nominal",
                title: null,
                axis: { labelAngle: -30 },
              },
              y: { field: primaryMetric, type: "quantitative", title: null },
              color: {
                field: dimensionKey,
                type: "nominal",
                scale: { range: COLORS },
                legend: null,
              },
              tooltip: [
                { field: dimensionKey, type: "nominal" },
                { field: primaryMetric, type: "quantitative" },
              ],
            },
          };
        }
        break;
      }
    }

    return (
      <ChartErrorBoundary fallbackData={data}>
        <VegaEmbed
          spec={spec}
          options={{ actions: false }}
          style={{ width: "100%", height: "100%" }}
        />
      </ChartErrorBoundary>
    );
  };

  // Use h-auto for wide-to-long charts so they aren't clipped
  const isWideToLong =
    isSingleRowWide && pctKeys.length > 1 && type === "metric";

  // Map internal type -> user-friendly label
  const chartTypeLabelMap: Record<string, string> = {
    line: "Line Chart",
    bar: "Bar Chart",
    metric: "Metric",
    table: "Table",
  };

  const displayType = chartTypeLabelMap[type] ?? type;

  return (
    <div
      className={`w-full mt-4 bg-white/50 backdrop-blur-sm rounded-xl p-4 border border-gray-100 shadow-sm overflow-hidden ${
        isWideToLong ? "h-auto" : "h-64"
      }`}
    >
      {/* Visualization Type Header */}
      <div className="mb-3">
        <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">
          Visualization Type
        </p>
        <p className="text-sm font-semibold text-gray-800">{displayType}</p>
      </div>

      {renderChart()}
    </div>
  );
}
