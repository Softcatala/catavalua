import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, JoinColumn, Check } from 'typeorm';
import { Clip } from './clip.entity';

export type IssueReportStatus = 'open' | 'done';

// Raised by an evaluator from the evaluate page when something looks wrong
// with the clip/dimension they're currently looking at. dimension/dimensionValue
// are a snapshot of what was on screen at report time, not a live reference —
// e.g. for 'transcription', dimensionValue is the transcription text shown;
// for 'gender'/'dialect', it's the value shown (e.g. 'female', 'central').
@Entity('issue_reports')
@Check(`"message" IS NOT NULL AND length("message") <= 1000`)
export class IssueReport {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'clip_id' })
  clipId: string;

  @ManyToOne(() => Clip)
  @JoinColumn({ name: 'clip_id' })
  clip: Clip;

  @Column()
  dimension: string; // 'transcription' | 'gender' | 'dialect'

  @Column('text', { name: 'dimension_value', nullable: true })
  dimensionValue: string | null;

  @Column('varchar', { length: 1000 })
  message: string;

  @Column()
  username: string;

  @Column({ default: 'open' })
  status: IssueReportStatus;

  @Column({ name: 'created_at', nullable: true })
  createdAt: string;
}
