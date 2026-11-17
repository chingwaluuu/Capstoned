import http from 'k6/http';
import { check, sleep } from 'k6';

const baseUrl = (__ENV.BASE_URL || 'http://127.0.0.1:5001').replace(/\/$/, '');

export const options = {
  scenarios: {
    login_page_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 50 },
        { duration: '10s', target: 200 },
        { duration: '30s', target: 200 },
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<2500'],
  },
};

export default function () {
  const response = http.get(`${baseUrl}/login`, { timeout: '15s' });
  check(response, {
    'login page returns HTTP 200': (r) => r.status === 200,
    'login form is present': (r) => r.body && r.body.includes('name="email"'),
  });
  sleep(1);
}
