// Loaded via `node -r ./dist/tracing.js` BEFORE dist/main.js, so that
// auto-instrumentation can patch http/express/etc. before those modules are
// first required elsewhere. Do not import this from main.ts — importing it
// there would run it too late for the patching to take effect.
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions';

const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

// No collector configured (e.g. local dev) -> skip entirely rather than
// retrying failed exports forever in the background.
if (otlpEndpoint) {
  const sdk = new NodeSDK({
    resource: resourceFromAttributes({
      [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME || 'catavalua-backend',
    }),
    traceExporter: new OTLPTraceExporter({ url: otlpEndpoint }),
    instrumentations: [
      getNodeAutoInstrumentations({
        // Disable the fs instrumentation, it's extremely noisy (every static
        // file / migration read becomes a span) and not useful here.
        '@opentelemetry/instrumentation-fs': { enabled: false },
      }),
    ],
  });

  sdk.start();

  process.on('SIGTERM', () => {
    sdk.shutdown().finally(() => process.exit(0));
  });
}
