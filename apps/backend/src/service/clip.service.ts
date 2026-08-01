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
    // Get clip IDs this user has already voted on for this dimension
    const voted = username
      ? await this.votes.find({ where: { username, dimension }, select: ['clipId'] })
      : [];
    const excludeIds = [...new Set([...voted.map((v) => v.clipId), ...skipIds])];

    const baseWhere = '(clip.is_relevant IS NULL OR clip.is_relevant = 1)';

    const buildQb = (excludeIds: string[]) => {
      const qb = this.clips.createQueryBuilder('clip').where(baseWhere);
      if (excludeIds.length > 0) {
        qb.andWhere('clip.clip_id NOT IN (:...ids)', { ids: excludeIds });
      }
      return qb;
    };

    // For transcription dimension: prefer clips whose audio is actually
    // indexed (tar_file set), so the evaluator can listen rather than hit
    // "audio not indexed yet" — and among those, prefer 2+ model agreement
    // on the same text (a strong quality signal) when available.
    if (dimension === 'transcription') {
      const agreedAndIndexed = await buildQb(excludeIds)
        .andWhere('clip.tar_file IS NOT NULL')
        .andWhere(`clip.clip_id IN (
          SELECT t.clip_id FROM transcriptions t
          GROUP BY t.clip_id, t.text
          HAVING COUNT(*) >= 2
        )`)
        .orderBy('RANDOM()')
        .limit(1)
        .getOne();

      if (agreedAndIndexed) return agreedAndIndexed;

      const indexedOnly = await buildQb(excludeIds)
        .andWhere('clip.tar_file IS NOT NULL')
        .orderBy('RANDOM()')
        .limit(1)
        .getOne();

      if (indexedOnly) return indexedOnly;
    }

    // For gender: same audio-availability concern as transcription — prefer
    // clips the evaluator can actually listen to.
    if (dimension === 'gender') {
      const indexed = await buildQb(excludeIds)
        .andWhere('clip.tar_file IS NOT NULL')
        .orderBy('RANDOM()')
        .limit(1)
        .getOne();

      if (indexed) return indexed;
    }

    // For dialect: most clips have no dialect signal at all (no Gemini guess,
    // no town-derived vote — see scripts/infer_dialect.py), which sends the
    // evaluator to a dead-end clip with nothing to confirm/correct. Prefer
    // clips that DO have a signal — either clip.detected_dialect, or an
    // existing 'dialect' vote (e.g. from the bulk town-inference import) —
    // so evaluators mostly see clips they can actually act on.
    if (dimension === 'dialect') {
      const withSignal = await buildQb(excludeIds)
        .andWhere(`(clip.detected_dialect IS NOT NULL OR clip.clip_id IN (
          SELECT v.clip_id FROM votes v WHERE v.dimension = 'dialect'
        ))`)
        .orderBy('RANDOM()')
        .limit(1)
        .getOne();

      if (withSignal) return withSignal;
    }

    const result = await buildQb(excludeIds).orderBy('RANDOM()').limit(1).getOne();

    // If user has evaluated all clips, cycle back (but still exclude irrelevant)
    if (!result && excludeIds.length > 0) {
      return this.clips.createQueryBuilder('clip')
        .where(baseWhere)
        .orderBy('RANDOM()')
        .limit(1)
        .getOne();
    }

    return result;
  }

  async flagIrrelevant(clipId: string, username: string): Promise<void> {
    this.metrics.clipsFlaggedIrrelevantTotal.inc();
    // Record a "not_relevant" vote so we can track who flagged it
    await this.votes.save(
      this.votes.create({
        clipId,
        dimension: 'relevance',
        targetId: 'not_relevant',
        username,
        value: -1,
        createdAt: new Date().toISOString(),
      }),
    );
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
