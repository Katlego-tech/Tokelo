// perf/<name>.js: a performance test for the NFRs it names (the release runs every perf/*.js
// against staging). k6 fails the release when a threshold breaks, so the thresholds are the NFR
// targets from REQUIREMENTS.md. Each service's staging URL arrives as BASE_URL_<SERVICE>.
// req: NFR-001
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: 10,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],       // NFR-001: fewer than 1% errors
    http_req_duration: ['p(95)<200'],     // NFR-001: p95 under 200 ms
  },
};

export default function () {
  const res = http.get(`${__ENV.BASE_URL_API}/api/robots`);
  check(res, { 'answered 200': (r) => r.status === 200 });
}
