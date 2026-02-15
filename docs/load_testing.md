# Load Testing

## Goals
- Validate response latency under typical peak traffic.
- Ensure Cloud Run autoscaling behaves as expected.

## Suggested Tools
- `k6` or `hey` for HTTP load testing.

## Example (k6)
```
k6 run --vus 50 --duration 2m scripts/load_test.js
```

## Metrics to Track
- p95 latency
- error rate
- CPU/memory utilization
- Cloud Run instance count
