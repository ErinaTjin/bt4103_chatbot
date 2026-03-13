"use client";

import React from "react";
import { VegaEmbed } from "react-vega";
import { DataRow } from "@/lib/types";

// Standardizing colors to match the previous Recharts palette where possible
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
  type: "bar" | "line" | "pie" | string;
}

export function ResultsChart({ data, type }: ResultsChartProps) {
  if (!data || data.length === 0) return null;

  // Identify keys for charting
  // Typically, the first key is the dimension, and others are metrics
  const keys = Object.keys(data[0]);
  const dimensionKey = keys[0];
  const metricKeys = keys.slice(1);

  // Vega-Lite requires a slightly different data format if there are multiple metrics
  // to be displayed on the same chart (i.e. 'wide' to 'long' format folding).
  // However, assuming standard single-metric output for NL2SQL for simplicity,
  // or relying on primary metric if there are multiple.
  const primaryMetric = metricKeys[0];

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
        view: { stroke: "transparent" }, // Removes default border
        axis: {
          grid: false, // matches false cartesian grid
          domain: false, // equivalent to axisLine={false}
          ticks: false, // equivalent to tickLine={false}
          labelPadding: 10, // roughly equivalent to dy={10}
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
            axisY: { grid: true, gridDash: [3, 3] }, // Y grid only
          },
          mark: { type: "line", point: true, tooltip: true, strokeWidth: 2 },
          encoding: {
            x: { field: dimensionKey, type: "nominal", title: null },
            y: { field: primaryMetric, type: "quantitative", title: null },
            color: { value: COLORS[0] }, // Simplify to single color for single metric line
            tooltip: [
              { field: dimensionKey, type: "nominal" },
              { field: primaryMetric, type: "quantitative" },
            ],
          },
        };
        break;

      case "bar":
      default:
        spec = {
          ...spec,
          config: {
            ...spec.config,
            axisY: { grid: true, gridDash: [3, 3] }, // Y grid only
          },
          mark: { type: "bar", tooltip: true, cornerRadiusEnd: 4 },
          encoding: {
            x: {
              field: dimensionKey,
              type: "nominal",
              title: null,
              axis: { labelAngle: 0 },
            },
            y: { field: primaryMetric, type: "quantitative", title: null },
            color: {
              field: dimensionKey,
              type: "nominal",
              scale: { range: COLORS },
              legend: null, // Usually bar charts without groups don't need a legend in Vega
            },
            tooltip: [
              { field: dimensionKey, type: "nominal" },
              { field: primaryMetric, type: "quantitative" },
            ],
          },
        };
        break;
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
