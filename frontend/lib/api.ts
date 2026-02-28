import { QueryResponse } from './types';
import { mockSuccessResponse } from './mockData';

// API wrapper for backend communication
// Currently using mock data, need real API when backend is ready

export async function queryBackend(message: string): Promise<QueryResponse> {
  console.log('User query:', message);
  
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve(mockSuccessResponse);
    }, 1500); // Simulate API call with 1.5s delay
  });
}