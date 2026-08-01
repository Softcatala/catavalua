import { Injectable, NestMiddleware } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';
import { MetricsService } from './metrics.service';

// Middleware rather than an interceptor: interceptors run inside the
// request pipeline, before Nest's exception filter has written the final
// status code to the response, so an interceptor reading res.statusCode on
// an errored request sees the route's default success code, not the real
// one. `res.on('finish', ...)` fires only once the response is fully sent,
// so res.statusCode is always the real one by then.
@Injectable()
export class HttpMetricsMiddleware implements NestMiddleware {
  constructor(private readonly metrics: MetricsService) {}

  use(req: Request, res: Response, next: NextFunction): void {
    const start = process.hrtime.bigint();

    res.on('finish', () => {
      // req.route.path is the matched pattern (e.g. "/clips/:id"), not the raw
      // URL — keeps cardinality bounded regardless of how many distinct clipIds
      // are requested. Populated by Express once routing has happened, which
      // is guaranteed by the time 'finish' fires.
      const route = req.route?.path ? `${req.baseUrl}${req.route.path}` : req.path;
      const status = String(res.statusCode);
      const seconds = Number(process.hrtime.bigint() - start) / 1e9;

      this.metrics.httpRequestDuration.observe({ method: req.method, route, status }, seconds);
      this.metrics.httpRequestsTotal.inc({ method: req.method, route, status });
    });

    next();
  }
}
