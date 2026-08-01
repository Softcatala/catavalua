import { Injectable } from '@nestjs/common';
import * as client from 'prom-client';

// Single global registry for the process. Business counters live here rather
// than being scattered per-service so /metrics stays one coherent surface —
// mirrors the "expose our own /metrics, Prometheus scrapes it directly"
// approach used by the other softcatala services on docker/monitor.
@Injectable()
export class MetricsService {
  readonly registry = new client.Registry();

  readonly httpRequestDuration = new client.Histogram({
    name: 'catvoice_http_request_duration_seconds',
    help: 'HTTP request duration in seconds',
    labelNames: ['method', 'route', 'status'],
    buckets: [0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5],
    registers: [this.registry],
  });

  readonly httpRequestsTotal = new client.Counter({
    name: 'catvoice_http_requests_total',
    help: 'Total HTTP requests',
    labelNames: ['method', 'route', 'status'],
    registers: [this.registry],
  });

  readonly votesCastTotal = new client.Counter({
    name: 'catvoice_votes_cast_total',
    help: 'Votes cast, by dimension and direction',
    labelNames: ['dimension', 'value'],
    registers: [this.registry],
  });

  readonly clipsGoldenTotal = new client.Gauge({
    name: 'catvoice_clips_golden_total',
    help: 'Clips whose net votes have reached the golden threshold, by dimension',
    labelNames: ['dimension'],
    registers: [this.registry],
  });

  readonly transcriptionsIngestedTotal = new client.Counter({
    name: 'catvoice_transcriptions_ingested_total',
    help: 'Transcriptions ingested via POST /transcriptions, by origin and whether it was a new row',
    labelNames: ['origin', 'outcome'], // outcome: created | duplicate
    registers: [this.registry],
  });

  readonly issueReportsTotal = new client.Counter({
    name: 'catvoice_issue_reports_total',
    help: 'Issue reports filed, by dimension',
    labelNames: ['dimension'],
    registers: [this.registry],
  });

  readonly clipsFlaggedIrrelevantTotal = new client.Counter({
    name: 'catvoice_clips_flagged_irrelevant_total',
    help: 'Clips flagged as irrelevant, by reason',
    labelNames: ['reason'],
    registers: [this.registry],
  });

  readonly audioProxyRequestsTotal = new client.Counter({
    name: 'catvoice_audio_proxy_requests_total',
    help: 'Audio proxy requests, by outcome',
    labelNames: ['outcome'], // ok | not_found | upstream_error
    registers: [this.registry],
  });

  readonly audioProxyDuration = new client.Histogram({
    name: 'catvoice_audio_proxy_duration_seconds',
    help: 'Time to stream a clip from HuggingFace to the client',
    buckets: [0.1, 0.3, 0.5, 1, 2, 5, 10],
    registers: [this.registry],
  });

  readonly audioProxyBytesTotal = new client.Counter({
    name: 'catvoice_audio_proxy_bytes_total',
    help: 'Bytes streamed from the audio proxy',
    registers: [this.registry],
  });

  constructor() {
    client.collectDefaultMetrics({ register: this.registry });
  }
}
