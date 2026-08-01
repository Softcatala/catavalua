import { ConsoleLogger, LoggerService, LogLevel } from '@nestjs/common';
import { logs, SeverityNumber } from '@opentelemetry/api-logs';
import { LoggerProvider, BatchLogRecordProcessor } from '@opentelemetry/sdk-logs';
import { OTLPLogExporter } from '@opentelemetry/exporter-logs-otlp-grpc';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions';

const LEVEL_TO_SEVERITY: Record<LogLevel, SeverityNumber> = {
  verbose: SeverityNumber.TRACE,
  debug: SeverityNumber.DEBUG,
  log: SeverityNumber.INFO,
  warn: SeverityNumber.WARN,
  error: SeverityNumber.ERROR,
  fatal: SeverityNumber.FATAL,
};

// Wraps Nest's own console logging so every existing `this.logger.log(...)`
// call site keeps working unchanged, and also ships the same record to the
// OTel Collector -> Loki. No-ops the OTel side when no collector is
// configured, so local dev still just prints to the console as before.
export class OtelLogger extends ConsoleLogger implements LoggerService {
  private readonly otelLogger = process.env.OTEL_EXPORTER_OTLP_ENDPOINT
    ? (() => {
        const provider = new LoggerProvider({
          resource: resourceFromAttributes({
            [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME || 'catavalua-backend',
          }),
          processors: [
            new BatchLogRecordProcessor({
              exporter: new OTLPLogExporter({ url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT }),
            }),
          ],
        });
        logs.setGlobalLoggerProvider(provider);
        return logs.getLogger('catavalua-backend');
      })()
    : null;

  protected printMessages(
    messages: unknown[],
    context?: string,
    logLevel: LogLevel = 'log',
  ): void {
    super.printMessages(messages, context, logLevel);

    this.otelLogger?.emit({
      severityNumber: LEVEL_TO_SEVERITY[logLevel],
      severityText: logLevel,
      body: messages.map((m) => (typeof m === 'string' ? m : JSON.stringify(m))).join(' '),
      attributes: context ? { context } : undefined,
    });
  }
}
