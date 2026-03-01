// This is the mock data, can delete this once backend is connected

import { QueryResponse, Filter } from './types';

const sampleFilters: Filter[] = [
  { field: "cancer_type", op: "=", value: "colorectal cancer" },
  { field: "year", op: "=", value: "2021" }
];

export const mockPieResponse: QueryResponse = {
  data: [
    { stage: "I", count_patients: 45 },
    { stage: "II", count_patients: 120 },
    { stage: "III", count_patients: 89 },
    { stage: "IV", count_patients: 34 }
  ],
  sql: "SELECT stage, COUNT(*) AS count_patients FROM anchor_view WHERE cancer_type = 'colorectal cancer' AND year = '2021' GROUP BY stage ORDER BY count_patients DESC LIMIT 50",
  query_plan: {
    intent: "distribution",
    metric: "count_patients",
    dimensions: ["stage"],
    filters: sampleFilters,
    limit: 50,
    output: { preferred_visualization: "pie" },
    needs_clarification: false,
    clarification_question: null
  },
  guardrails: { ok: true, warnings: [] },
  warnings: []
};

export const mockBarResponse: QueryResponse = {
  data: [
    { cancer_type: "Colorectal", count_patients: 450 },
    { cancer_type: "Breast", count_patients: 320 },
    { cancer_type: "Lung", count_patients: 289 },
    { cancer_type: "Prostate", count_patients: 234 }
  ],
  sql: "SELECT cancer_type, COUNT(*) AS count_patients FROM anchor_view GROUP BY cancer_type ORDER BY count_patients DESC LIMIT 10",
  query_plan: {
    intent: "topN",
    metric: "count_patients",
    dimensions: ["cancer_type"],
    filters: [],
    limit: 10,
    output: { preferred_visualization: "bar" },
    needs_clarification: false,
    clarification_question: null
  },
  guardrails: { ok: true, warnings: [] },
  warnings: []
};

export const mockLineResponse: QueryResponse = {
  data: [
    { year: 2018, count_patients: 1200 },
    { year: 2019, count_patients: 1350 },
    { year: 2020, count_patients: 1100 },
    { year: 2021, count_patients: 1420 },
    { year: 2022, count_patients: 1580 }
  ],
  sql: "SELECT year, COUNT(*) AS count_patients FROM anchor_view GROUP BY year ORDER BY year ASC",
  query_plan: {
    intent: "trend",
    metric: "count_patients",
    dimensions: ["year"],
    filters: [],
    limit: 50,
    output: { preferred_visualization: "line" },
    needs_clarification: false,
    clarification_question: null
  },
  guardrails: { ok: true, warnings: [] },
  warnings: []
};

export const mockTableResponse: QueryResponse = {
  data: [
    { patient_id: "P001", age: 65, gender: "M", stage: "II" },
    { patient_id: "P002", age: 54, gender: "F", stage: "I" },
    { patient_id: "P003", age: 72, gender: "M", stage: "IV" },
    { patient_id: "P004", age: 48, gender: "F", stage: "III" }
  ],
  sql: "SELECT patient_id, age, gender, stage FROM anchor_view LIMIT 4",
  query_plan: {
    intent: "unsupported",
    metric: "raw_data",
    dimensions: ["patient_id", "age", "gender", "stage"],
    filters: [],
    limit: 4,
    output: { preferred_visualization: "table" },
    needs_clarification: false,
    clarification_question: null
  },
  guardrails: { ok: true, warnings: [] },
  warnings: []
};

export const mockSuccessResponse = mockPieResponse;