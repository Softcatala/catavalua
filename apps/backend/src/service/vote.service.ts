import { Injectable, ConflictException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { IsNull, Repository } from 'typeorm';
import { Vote } from '../domain/vote.entity';
import { Clip } from '../domain/clip.entity';

export interface VoteSummary {
  dimension: string;
  targetId: string | null;
  netVotes: number;
  isGolden: boolean;
}

// Usernames used by scripts that cast votes programmatically rather than
// real evaluators (e.g. scripts/infer_dialect.py's town-derived dialect
// votes). Their votes still count normally everywhere else — including
// summaryForClip/resolveDimension, so they still surface as a candidate for
// a human to confirm or reject — but stats() excludes them so evaluation
// progress reflects actual human review, not bulk-imported suggestions.
const SYSTEM_VOTE_USERNAMES = ['derivat-de-poblacio'];

@Injectable()
export class VoteService {
  constructor(
    @InjectRepository(Vote) private readonly repo: Repository<Vote>,
    @InjectRepository(Clip) private readonly clips: Repository<Clip>,
  ) {}

  async cast(data: {
    clipId: string;
    dimension: string;
    targetId?: string;
    username: string;
    value: number; // +1 or -1
  }): Promise<Vote> {
    // Upsert: one vote per user per clip per dimension per target — this lets a
    // user hold independent votes on competing candidates within the same dimension
    // (e.g. downvoting the current gender while upvoting the proposed alternative).
    const existing = await this.repo.findOne({
      where: {
        clipId: data.clipId,
        dimension: data.dimension,
        targetId: data.targetId ?? IsNull(),
        username: data.username,
      },
    });
    if (existing) {
      existing.value = data.value;
      existing.createdAt = new Date().toISOString();
      return this.repo.save(existing);
    }
    const vote = this.repo.create({
      ...data,
      createdAt: new Date().toISOString(),
    });
    return this.repo.save(vote);
  }

  async removeByUser(username: string): Promise<void> {
    await this.repo.delete({ username });
  }

  async summaryForClip(clipId: string): Promise<VoteSummary[]> {
    const votes = await this.repo.find({ where: { clipId } });

    // Group by dimension + targetId
    const map: Record<string, { dimension: string; targetId: string | null; net: number }> = {};
    for (const v of votes) {
      const key = `${v.dimension}::${v.targetId ?? ''}`;
      if (!map[key]) map[key] = { dimension: v.dimension, targetId: v.targetId, net: 0 };
      map[key].net += v.value;
    }

    return Object.values(map).map((entry) => ({
      dimension: entry.dimension,
      targetId: entry.targetId,
      netVotes: entry.net,
      isGolden: entry.net >= 2,
    }));
  }

  async userVotesForClip(clipId: string, username: string): Promise<Vote[]> {
    return this.repo.find({ where: { clipId, username } });
  }

  async stats(): Promise<{
    dimensions: { dimension: string; evaluated: number; golden: number; evaluatedHours: number; goldenHours: number }[];
    flaggedIrrelevant: number;
    totalHours: number;
  }> {
    const rows = await this.repo
      .createQueryBuilder('v')
      .innerJoin('v.clip', 'c')
      .select('v.dimension', 'dimension')
      .addSelect('v.clip_id', 'clipId')
      .addSelect('SUM(v.value)', 'net')
      .addSelect('c.duration', 'duration')
      .where('v.username NOT IN (:...usernames)', { usernames: SYSTEM_VOTE_USERNAMES })
      .groupBy('v.dimension')
      .addGroupBy('v.clip_id')
      .addGroupBy('c.duration')
      .getRawMany<{ dimension: string; clipId: string; net: string; duration: string | null }>();

    const map: Record<string, { evaluated: number; golden: number; evaluatedSeconds: number; goldenSeconds: number }> = {};
    let flaggedIrrelevant = 0;

    for (const row of rows) {
      const d = row.dimension;
      if (d === 'relevance') {
        flaggedIrrelevant++;
        continue;
      }
      if (!map[d]) map[d] = { evaluated: 0, golden: 0, evaluatedSeconds: 0, goldenSeconds: 0 };
      const seconds = Number(row.duration) || 0;
      map[d].evaluated++;
      map[d].evaluatedSeconds += seconds;
      if (Number(row.net) >= 2) {
        map[d].golden++;
        map[d].goldenSeconds += seconds;
      }
    }

    const dimensions = Object.entries(map).map(([dimension, { evaluated, golden, evaluatedSeconds, goldenSeconds }]) => ({
      dimension,
      evaluated,
      golden,
      evaluatedHours: evaluatedSeconds / 3600,
      goldenHours: goldenSeconds / 3600,
    }));

    const totalRow = await this.clips
      .createQueryBuilder('c')
      .select('SUM(c.duration)', 'total')
      .getRawOne<{ total: string | null }>();
    const totalHours = (Number(totalRow?.total) || 0) / 3600;

    return { dimensions, flaggedIrrelevant, totalHours };
  }
}
