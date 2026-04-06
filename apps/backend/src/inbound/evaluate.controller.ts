import { Controller, Get, Query, Param, NotFoundException } from '@nestjs/common';
import { ClipService } from '../service/clip.service';
import { TranscriptionService } from '../service/transcription.service';
import { VoteService } from '../service/vote.service';
import { Transcription } from '../domain/transcription.entity';

export interface UniqueTranscription {
  // ID of the first transcription with this text (used as vote targetId)
  representativeId: number;
  text: string;
  origins: string[];
  // True when 2+ distinct models produced exactly this string
  hasAgreement: boolean;
}

function deduplicateTranscriptions(transcriptions: Transcription[]): UniqueTranscription[] {
  const byText = new Map<string, UniqueTranscription>();

  for (const t of transcriptions) {
    const existing = byText.get(t.text);
    if (existing) {
      if (!existing.origins.includes(t.origin)) {
        existing.origins.push(t.origin);
        existing.hasAgreement = existing.origins.length >= 2;
      }
    } else {
      byText.set(t.text, {
        representativeId: t.id,
        text: t.text,
        origins: [t.origin],
        hasAgreement: false,
      });
    }
  }

  // Sort: agreed-upon texts first, then by representative ID
  return [...byText.values()].sort((a, b) => {
    if (a.hasAgreement !== b.hasAgreement) return a.hasAgreement ? -1 : 1;
    return a.representativeId - b.representativeId;
  });
}

@Controller('evaluate')
export class EvaluateController {
  constructor(
    private readonly clipService: ClipService,
    private readonly transcriptionService: TranscriptionService,
    private readonly voteService: VoteService,
  ) {}

  @Get('clip/:clipId')
  async forClip(
    @Param('clipId') clipId: string,
    @Query('username') username = '',
  ) {
    const result = await this.clipService.findOne(clipId).catch(() => null);
    if (!result) throw new NotFoundException(`Clip ${clipId} not found`);
    const rawTranscriptions = await this.transcriptionService.findByClip(clipId);
    const uniqueTranscriptions = deduplicateTranscriptions(rawTranscriptions);
    const votes = await this.voteService.summaryForClip(clipId);
    const userVotes = username ? await this.voteService.userVotesForClip(clipId, username) : [];
    return { clip: result.clip, uniqueTranscriptions, votes, userVotes };
  }

  @Get('next')
  async next(
    @Query('username') username: string,
    @Query('dimension') dimension = 'transcription',
    @Query('skip') skipRaw = '',
  ) {
    const skipIds = skipRaw ? skipRaw.split(',').filter(Boolean) : [];

    const clip = await this.clipService.nextForEvaluation(username, dimension, skipIds);
    if (!clip) return { done: true };

    const rawTranscriptions = await this.transcriptionService.findByClip(clip.clipId);
    const uniqueTranscriptions = deduplicateTranscriptions(rawTranscriptions);

    const votes = await this.voteService.summaryForClip(clip.clipId);
    const userVotes = username ? await this.voteService.userVotesForClip(clip.clipId, username) : [];

    return { clip, uniqueTranscriptions, votes, userVotes };
  }
}
