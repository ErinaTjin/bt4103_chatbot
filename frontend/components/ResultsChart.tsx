"use client";

import React from "react";
import { VegaEmbed } from "react-vega";
import { DataRow } from "../lib/types";

const COLORS = [
  "#0088FE",
  "#00C49F",
  "#FFBB28",
  "#FF8042",
  "#8884d8",
  "#82ca9d",
];

interface ResultsChartProps {
  data: DataRow[];
  type: "bar" | "line" | "pie" | "metric" | string;
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

  const renderChart = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let spec: Record<string, any> = {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
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
        spec = {
          ...spec,
          config: {
            ...spec.config,
            axisY: { grid: true, gridDash: [3, 3] },
          },
          layer: [
            {
              mark: {
                type: "line",
                strokeWidth: 2.5,
                color: COLORS[0],
                interpolate: "monotone",
              },
              encoding: {
                x: {
                  field: dimensionKey,
                  type: "ordinal",
                  title: null,
                  axis: { labelAngle: -30 },
                },
                y: {
                  field: primaryMetric,
                  type: "quantitative",
                  title: null,
                  scale: { zero: false },
                },
              },
            },
            {
              mark: {
                type: "point",
                filled: true,
                size: 60,
                color: COLORS[0],
              },
              encoding: {
                x: { field: dimensionKey, type: "ordinal" },
                y: { field: primaryMetric, type: "quantitative" },
                tooltip: [
                  { field: dimensionKey, type: "ordinal", title: dimensionKey.replace(/_/g, " ") },
                  { field: primaryMetric, type: "quantitative", title: primaryMetric.replace(/_/g, " ") },
                ],
              },
            },
          ],
        };
        break;

      case "metric": {
        const value = data[0]?.[primaryMetric] ?? 0;
        return (
          <div className="flex items-center justify-center w-full h-64 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-100 p-8">
            <div className="text-center">
              <p className="text-sm text-gray-500 uppercase tracking-widest font-semibold mb-4">
                Result
              </p>
              <p className="text-6xl font-bold text-blue-600 mb-2">
                {typeof value === "number" ? value.toLocaleString() : value}
              </p>
              <p className="text-xs text-gray-400 uppercase tracking-widest">
                {primaryMetric}
              </p>
            </div>
          </div>
        );
      }

      case "bar":
      default: {
        // Detect cohort comparison: 2+ dimension columns before the metric
        // e.g. [gender, age_group, count_patients] → grouped bar chart
        const numericKeys = keys.filter(
          (k) => typeof data[0][k] === "number"
        );
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
              ...spec.config,
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
                { field: xDim, type: "nominal", title: xDim.replace(/_/g, " ") },
                { field: colorDim, type: "nominal", title: colorDim.replace(/_/g, " ") },
                { field: metric, type: "quantitative", title: metric.replace(/_/g, " ") },
              ],
            },
          };
        } else {
          // Simple single-dimension bar chart (original behaviour)
          spec = {
            ...spec,
            config: {
              ...spec.config,
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
      <VegaEmbed
        spec={spec}
        options={{ actions: false }}
        style={{ width: "100%", height: "100%" }}
      />
    );
  };

  return (
    <div className="w-full h-64 mt-4 bg-white/50 backdrop-blur-sm rounded-xl p-4 border border-gray-100 shadow-sm overflow-hidden">
      {renderChart()}
    </div>
  );
}
