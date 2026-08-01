import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, Like } from 'typeorm';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';
import { Vote } from '../domain/vote.entity';
import { IssueReport } from '../domain/issue-report.entity';
import { MetricsService } from '../observability/metrics.service';

export interface ClipWithBest {
  clip: Clip;
  bestTranscription: Transcription | null;
  voteSummary: Record<string, number>; // dimension -> net votes for golden item
}

// Categories for why a clip was flagged irrelevant, stored as the 'relevance'
// vote's targetId — lets us tell "not Catalan" apart from "multiple speakers"
// etc. for future post-processing (e.g. splitting multi-speaker clips).
export const IRRELEVANT_REASONS = [
  'not_catalan',
  'multiple_speakers',
  'code_switching',
  'no_speech',
  'unintelligible',
] as const;
export type IrrelevantReason = (typeof IRRELEVANT_REASONS)[number];

@Injectable()
export class ClipService {
  constructor(
    @InjectRepository(Clip) private readonly clips: Repository<Clip>,
    @InjectRepository(Transcription) private readonly transcriptions: Repository<Transcription>,
    @InjectRepository(Vote) private readonly votes: Repository<Vote>,
    @InjectRepository(IssueReport) private readonly issueReports: Repository<IssueReport>,
    private readonly metrics: MetricsService,
  ) {}

  async list(search: string, page: number, limit: number): Promise<{ items: ClipWithBest[]; total: number }> {
    const where = search
      ? [
          { candidate1: Like(`%${search}%`) },
          { candidate2: Like(`%${search}%`) },
          { clipId: Like(`%${search}%`) },
        ]
      : undefined;

    const [clips, total] = await this.clips.findAndCount({
      where,
      skip: (page - 1) * limit,
      take: limit,
      order: { clipId: 'ASC' },
    });

    const items = await Promise.all(clips.map((c) => this.enrichClip(c)));
    return { items, total };
  }

  async findOne(clipId: string): Promise<ClipWithBest> {
    const clip = await this.clips.findOne({ where: { clipId } });
    if (!clip) throw new NotFoundException(`Clip ${clipId} not found`);
    return this.enrichClip(clip);
  }

  async upsert(data: Partial<Clip>): Promise<Clip> {
    await this.clips.upsert(data as Clip, ['clipId']);
    return this.clips.findOneOrFail({ where: { clipId: data.clipId! } });
  }

  async updateTarIndex(clipId: string, tarFile: number, tarOffset: number, tarSize: number): Promise<void> {
    await this.clips.update({ clipId }, { tarFile, tarOffset, tarSize });
  }

  async remove(clipId: string): Promise<void> {
    const clip = await this.clips.findOne({ where: { clipId } });
    if (!clip) throw new NotFoundException(`Clip ${clipId} not found`);
    // FKs are ON DELETE NO ACTION, so children must go first.
    await this.votes.delete({ clipId });
    await this.transcriptions.delete({ clipId });
    await this.issueReports.delete({ clipId });
    await this.clips.delete({ clipId });
  }

  // Returns clips that the given username hasn't voted on for the given dimension
  async nextForEvaluation(username: string, dimension: string, skipIds: string[] = []): Promise<Clip | null> {
    // tar_file IS NOT NULL: never send the evaluator to a clip with no
    // indexed audio — there'd be nothing to listen to.
    const baseWhere = "(clip.is_relevant IS NULL OR clip.is_relevant = 1) AND clip.tar_file IS NOT NULL";
    const baseQb = () => this.clips.createQueryBuilder('clip').where(baseWhere);

    // Any extra predicate on top of baseWhere here — a NOT IN/NOT EXISTS
    // exclusion, the dialect-signal filter below — makes SQLite fall off
    // the fast path for `ORDER BY RANDOM() LIMIT n` on a clips-sized table:
    // benchmarked at 150-200ms with only baseWhere vs. 1.4-2s+ with one
    // more AND clause added, *regardless* of which clause (confirmed this
    // isn't NOT IN specifically — NOT EXISTS and a LEFT JOIN anti-join cost
    // the same). So: sample randomly with only baseWhere (cheap — LIMIT
    // barely matters, the cost is the sort, not rows returned), then apply
    // exclusion/preference against the sample in application code.
    const SAMPLE_SIZE = 200;

    const excludedIds = new Set<string>(skipIds);
    if (username) {
      const voted = await this.votes.find({ where: { username, dimension }, select: ['clipId'] });
      for (const v of voted) excludedIds.add(v.clipId);
    }

    const sample = await baseQb().orderBy('RANDOM()').limit(SAMPLE_SIZE).getMany();
    const candidates = sample.filter((c) => !excludedIds.has(c.clipId));

    if (candidates.length > 0) {
      // For dialect: most clips have no dialect signal at all (no Gemini
      // guess, no town-derived vote — see scripts/infer_dialect.py), which
      // sends the evaluator to a dead-end clip with nothing to
      // confirm/correct. Prefer clips that DO have a signal — either
      // clip.detected_dialect, or an existing 'dialect' vote (e.g. from the
      // bulk town-inference import) — scoped to just this sample's ids so
      // it stays a cheap indexed lookup instead of pulling every
      // dialect-voted clip in the database.
      if (dimension === 'dialect') {
        const withoutOwnSignal = candidates.filter((c) => !c.detectedDialect);
        const signalIds =
          withoutOwnSignal.length > 0
            ? new Set(
                (
                  await this.votes
                    .createQueryBuilder('v')
                    .select('DISTINCT v.clip_id', 'clipId')
                    .where('v.dimension = :dimension', { dimension: 'dialect' })
                    .andWhere('v.clip_id IN (:...ids)', { ids: withoutOwnSignal.map((c) => c.clipId) })
                    .getRawMany<{ clipId: string }>()
                ).map((v) => v.clipId),
              )
            : new Set<string>();
        const withSignal = candidates.find((c) => c.detectedDialect || signalIds.has(c.clipId));
        if (withSignal) return withSignal;
      }

      return candidates[Math.floor(Math.random() * candidates.length)];
    }

    // The sample was exhausted entirely by exclusions (this user has voted
    // on most of what currently matches baseWhere) — fall back to the
    // accurate, exclusion-filtered query. Same cost profile as above
    // (1-2s), but rare: only hit once a user nears the end of the dataset.
    const excludedList = [...excludedIds];
    const fallbackQb = baseQb();
    if (excludedList.length > 0) {
      fallbackQb.andWhere('clip.clip_id NOT IN (:...ids)', { ids: excludedList });
    }
    const fallback = await fallbackQb.orderBy('RANDOM()').limit(1).getOne();
    if (fallback) return fallback;

    // If user has evaluated all clips, cycle back (but still exclude irrelevant)
    if (excludedList.length > 0) {
      return baseQb().orderBy('RANDOM()').limit(1).getOne();
    }

    return null;
  }

  async flagIrrelevant(clipId: string, username: string, reason: IrrelevantReason): Promise<void> {
    this.metrics.clipsFlaggedIrrelevantTotal.inc({ reason });
    // One 'relevance' vote per user per clip, regardless of reason — if the
    // user already flagged this clip (perhaps with a different reason), update
    // it in place rather than inserting a second row for the same opinion.
    const existing = await this.votes.findOne({ where: { clipId, dimension: 'relevance', username } });
    if (existing) {
      await this.votes.update(existing.id, { targetId: reason, value: -1, createdAt: new Date().toISOString() });
    } else {
      await this.votes.save(
        this.votes.create({
          clipId,
          dimension: 'relevance',
          targetId: reason,
          username,
          value: -1,
          createdAt: new Date().toISOString(),
        }),
      );
    }
    // If 2+ users flag it, mark it irrelevant
    const flags = await this.votes.count({ where: { clipId, dimension: 'relevance', value: -1 } });
    if (flags >= 2) {
      await this.clips.update({ clipId }, { isRelevant: false });
    }
  }

  private async enrichClip(clip: Clip): Promise<ClipWithBest> {
    const allTranscriptions = await this.transcriptions.find({
      where: { clipId: clip.clipId },
      order: { id: 'ASC' },
    });

    // Best transcription: pick by net votes, fall back to first non-candidate, then first candidate
    const allVotes = await this.votes.find({ where: { clipId: clip.clipId, dimension: 'transcription' } });
    const netByTarget: Record<string, number> = {};
    for (const v of allVotes) {
      if (v.targetId) {
        netByTarget[v.targetId] = (netByTarget[v.targetId] ?? 0) + v.value;
      }
    }

    let bestTranscription: Transcription | null = null;
    let bestNet = -Infinity;
    for (const t of allTranscriptions) {
      const net = netByTarget[String(t.id)] ?? 0;
      if (net > bestNet) {
        bestNet = net;
        bestTranscription = t;
      }
    }
    if (!bestTranscription && allTranscriptions.length > 0) {
      bestTranscription = allTranscriptions.find((t) => !t.origin.startsWith('candidate')) ?? allTranscriptions[0];
    }

    // Vote summary: dimension -> net votes for the winning target
    const voteSummary: Record<string, number> = {};
    for (const [targetId, net] of Object.entries(netByTarget)) {
      voteSummary['transcription'] = Math.max(voteSummary['transcription'] ?? 0, net);
    }
    const genderVotes = await this.votes.find({ where: { clipId: clip.clipId, dimension: 'gender' } });
    voteSummary['gender'] = genderVotes.reduce((s, v) => s + v.value, 0);

    return { clip, bestTranscription, voteSummary };
  }
}
