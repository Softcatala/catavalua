import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Transcription } from '../domain/transcription.entity';

@Injectable()
export class TranscriptionService {
  constructor(
    @InjectRepository(Transcription) private readonly repo: Repository<Transcription>,
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
    if (existing) return existing;

    const t = this.repo.create({
      ...data,
      createdAt: new Date().toISOString(),
    });
    return this.repo.save(t);
  }

  async findByClip(clipId: string): Promise<Transcription[]> {
    return this.repo.find({ where: { clipId }, order: { id: 'ASC' } });
  }

  async hasOrigin(clipId: string, origin: string): Promise<boolean> {
    const count = await this.repo.count({ where: { clipId, origin } });
    return count > 0;
  }
}
