import { Entity, PrimaryColumn, Column, OneToMany, Index } from 'typeorm';
import { Transcription } from './transcription.entity';
import { Vote } from './vote.entity';

@Entity('clips')
// Matches nextForEvaluation's base filter (is_relevant/tar_file), so picking
// a candidate clip is an index scan instead of a full table scan.
@Index(['isRelevant', 'tarFile'])
// Matches the dialect-signal preference in nextForEvaluation.
@Index(['detectedDialect'])
export class Clip {
  @PrimaryColumn({ name: 'clip_id' })
  clipId: string;

  @Column({ name: 'source_id', nullable: true })
  sourceId: string;

  @Column('real', { nullable: true })
  duration: number;

  @Column('real', { nullable: true })
  start: number;

  @Column('real', { nullable: true })
  end: number;

  @Column({ nullable: true })
  gender: string;

  @Column('text', { name: 'candidate_1', nullable: true })
  candidate1: string;

  @Column('text', { name: 'candidate_2', nullable: true })
  candidate2: string;

  @Column({ name: 'yt_url', nullable: true })
  ytUrl: string;

  @Column({ nullable: true })
  license: string;

  // Language/dialect detected by models — populated by transcription script
  @Column({ name: 'detected_dialect', nullable: true })
  detectedDialect: string;

  @Column({ name: 'detected_language', nullable: true })
  detectedLanguage: string;

  // false = non-Catalan or otherwise irrelevant — excluded from golden dataset
  @Column({ name: 'is_relevant', type: 'integer', nullable: true, default: null })
  isRelevant: boolean | null;

  // TAR index — populated by the indexing script
  @Column({ name: 'tar_file', type: 'integer', nullable: true })
  tarFile: number;

  @Column({ name: 'tar_offset', type: 'integer', nullable: true })
  tarOffset: number;

  @Column({ name: 'tar_size', type: 'integer', nullable: true })
  tarSize: number;

  @OneToMany(() => Transcription, (t) => t.clip, { eager: false })
  transcriptions: Transcription[];

  @OneToMany(() => Vote, (v) => v.clip, { eager: false })
  votes: Vote[];
}
