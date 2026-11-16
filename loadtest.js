import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = 'http://127.0.0.1:5001';
const MAX_RESULT_ID = 50; // change to your highest result ID

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m',  target: 10 },
    { duration: '30s', target: 50 },
    { duration: '1m',  target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed:   ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const id = Math.floor(Math.random() * MAX_RESULT_ID) + 1;
  const res = http.get(`${BASE}/results/${id}`);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'no traceback': (r) => r.body !== null && !r.body.includes('Traceback'),
    'no ValueError': (r) => r.body !== null && !r.body.includes('ValueError'),
  });

  sleep(1);
}
