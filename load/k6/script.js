import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://store-api:8000';

export const options = {
  discardResponseBodies: true,
  scenarios: {
    browse: {
      executor: 'constant-arrival-rate',
      rate: 8, timeUnit: '1s', duration: '24h',
      preAllocatedVUs: 10, maxVUs: 60, exec: 'browse',
    },
    checkout: {
      executor: 'constant-arrival-rate',
      rate: 2, timeUnit: '1s', duration: '24h',
      preAllocatedVUs: 5, maxVUs: 30, exec: 'checkout',
    },
    homepage: {
      executor: 'constant-arrival-rate',
      rate: 1, timeUnit: '1s', duration: '24h',
      preAllocatedVUs: 2, maxVUs: 5, exec: 'home',
    },
  },
};

export function browse() {
  const r = http.get(`${BASE}/api/products`);
  check(r, { 'products 200': (x) => x.status === 200 });
}

export function checkout() {
  const body = JSON.stringify({ item_id: Math.ceil(Math.random() * 10), qty: 1 });
  http.post(`${BASE}/api/checkout`, body, { headers: { 'Content-Type': 'application/json' } });
}

export function home() {
  http.get(`${BASE}/`);
}
