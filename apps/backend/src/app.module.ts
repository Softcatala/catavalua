import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { getDatabaseConfig } from './config/database.config';
import { Clip } from './domain/clip.entity';
import { Transcription } from './domain/transcription.entity';
import { Vote } from './domain/vote.entity';
import { IssueReport } from './domain/issue-report.entity';
import { ClipService } from './service/clip.service';
import { TranscriptionService } from './service/transcription.service';
import { VoteService } from './service/vote.service';
import { IssueReportService } from './service/issue-report.service';
import { AudioProxyService } from './outbound/audio-proxy.service';
import { ClipController } from './inbound/clip.controller';
import { TranscriptionController } from './inbound/transcription.controller';
import { VoteController } from './inbound/vote.controller';
import { EvaluateController } from './inbound/evaluate.controller';
import { AudioController } from './inbound/audio.controller';
import { IssueReportController } from './inbound/issue-report.controller';
import { MetricsController } from './observability/metrics.controller';
import { MetricsService } from './observability/metrics.service';
import { HttpMetricsMiddleware } from './observability/http-metrics.middleware';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, envFilePath: '.env' }),
    TypeOrmModule.forRoot(getDatabaseConfig()),
    TypeOrmModule.forFeature([Clip, Transcription, Vote, IssueReport]),
  ],
  controllers: [
    ClipController,
    TranscriptionController,
    VoteController,
    EvaluateController,
    AudioController,
    IssueReportController,
    MetricsController,
  ],
  providers: [
    ClipService,
    TranscriptionService,
    VoteService,
    IssueReportService,
    AudioProxyService,
    MetricsService,
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    consumer.apply(HttpMetricsMiddleware).forRoutes('*');
  }
}
