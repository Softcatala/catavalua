import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { getDatabaseConfig } from './config/database.config';
import { Clip } from './domain/clip.entity';
import { Transcription } from './domain/transcription.entity';
import { Vote } from './domain/vote.entity';
import { ClipService } from './service/clip.service';
import { TranscriptionService } from './service/transcription.service';
import { VoteService } from './service/vote.service';
import { AudioProxyService } from './outbound/audio-proxy.service';
import { ClipController } from './inbound/clip.controller';
import { TranscriptionController } from './inbound/transcription.controller';
import { VoteController } from './inbound/vote.controller';
import { EvaluateController } from './inbound/evaluate.controller';
import { AudioController } from './inbound/audio.controller';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, envFilePath: '.env' }),
    TypeOrmModule.forRoot(getDatabaseConfig()),
    TypeOrmModule.forFeature([Clip, Transcription, Vote]),
  ],
  controllers: [
    ClipController,
    TranscriptionController,
    VoteController,
    EvaluateController,
    AudioController,
  ],
  providers: [ClipService, TranscriptionService, VoteService, AudioProxyService],
})
export class AppModule {}
