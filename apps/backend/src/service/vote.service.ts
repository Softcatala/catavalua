import { Injectable, ConflictException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Vote } from '../domain/vote.entity';

export interface VoteSummary {
  dimension: string;
  targetId: string | null;
  netVotes: number;
  isGolden: boolean;
}

@Injectable()
export class VoteService {
  constructor(
    @InjectRepository(Vote) private readonly repo: Repository<Vote>,
  ) {}

  async cast(data: {
    clipId: string;
    dimension: string;
    targetId?: string;
    username: string;
    value: number; // +1 or -1
  }): Promise<Vote> {
    // Upsert: one vote per user per clip per dimension
    const existing = await this.repo.findOne({
      where: { clipId: data.clipId, dimension: data.dimension, username: data.username },
    });
    if (existing) {
      existing.value = data.value;
      existing.targetId = data.targetId ?? existing.targetId;
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
}
