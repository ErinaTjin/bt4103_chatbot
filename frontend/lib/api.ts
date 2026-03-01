import { QueryResponse } from './types';
import * as mocks from './mockData';

// API wrapper for backend communication
// Logic-based mock mode for demonstration
export async function queryBackend(message: string): Promise<QueryResponse> {
  console.log('User query (Logic Mock):', message);
  const query = message.toLowerCase();

  let response = mocks.mockTableResponse;

  if (query.includes('pie')) {
    response = mocks.mockPieResponse;
  } else if (query.includes('bar')) {
    response = mocks.mockBarResponse;
  } else if (query.includes('line') || query.includes('trend')) {
    response = mocks.mockLineResponse;
  } else if (query.includes('stage') || query.includes('distribution')) {
    response = mocks.mockPieResponse; // default distribution to pie
  }

  return new Promise((resolve) => {
    setTimeout(() => {
      resolve(response);
    }, 1500); // Simulate network delay
  });
}