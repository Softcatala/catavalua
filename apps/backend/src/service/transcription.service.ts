import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Transcription } from '../domain/transcription.entity';
import { MetricsService } from '../observability/metrics.service';

@Injectable()
export class TranscriptionService {
  constructor(
    @InjectRepository(Transcription) private readonly repo: Repository<Transcription>,
    private readonly metrics: MetricsService,
  ) {}

  async create(data: {
    clipId: string;
    origin: string;
    text: string;
    metadata?: string;
  }): Promise<Transcription> {
    const existing = await this.repo.findOne({
      where: { clipId: data.clipId, origin: data.origin, text: data.text },
    });
    if (existing) {
      this.metrics.transcriptionsIngestedTotal.inc({ origin: data.origin, outcome: 'duplicate' });
      return existing;
    }

    const t = this.repo.create({
      ...data,
      createdAt: new Date().toISOString(),
    });
    const saved = await this.repo.save(t);
    this.metrics.transcriptionsIngestedTotal.inc({ origin: data.origin, outcome: 'created' });
    return saved;
  }

  async findByClip(clipId: string): Promise<Transcription[]> {
    return this.repo.find({ where: { clipId }, order: { id: 'ASC' } });
  }

  async hasOrigin(clipId: string, origin: string): Promise<boolean> {
    const count = await this.repo.count({ where: { clipId, origin } });
    return count > 0;
  }

  async remove(id: number): Promise<void> {
    const result = await this.repo.delete({ id });
    if (result.affected === 0) throw new NotFoundException(`Transcription ${id} not found`);
  }
}
