// This is the mock data, can delete this once backend is connected

import { QueryResponse, Intent, Filter } from './types';

const sampleFilters: Filter[] = [
  { field: "cancer_type", op: "=", value: "colorectal cancer" },
  { field: "year", op: "=", value: "2021" }
];

export const mockSuccessResponse: QueryResponse = {
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
    needs_clarification: false,
    clarification_question: null
  },
  guardrails: {
    ok: true,
    warnings: []
  },
  warnings: []
};